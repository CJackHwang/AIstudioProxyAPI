import json
import logging
import re
import zlib

class HttpInterceptor:
    """
    Class to intercept and process HTTP requests and responses
    """
    def __init__(self, log_dir='logs'):
        self.log_dir = log_dir
        self.logger = logging.getLogger('http_interceptor')
        self.setup_logging()
    
    @staticmethod
    def setup_logging():
        """Set up logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler()
            ]
        )
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        logging.getLogger('websockets').setLevel(logging.ERROR)
    
    @staticmethod
    def should_intercept(host, path):
        """
        Determine if the request should be intercepted based on host and path
        """
        # Check if the endpoint contains GenerateContent
        if 'GenerateContent' in path:
            return True
        
        # Add more conditions as needed
        return False
    
    async def process_request(self, request_data, host, path):
        """
        Process the request data before sending to the server
        """
        if not self.should_intercept(host, path):
            return request_data
        
        # Log the request
        self.logger.info(f"Intercepted request to {host}{path}")
        
        try:
            return request_data
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not JSON or not UTF-8, just pass through
            return request_data
    
    async def process_response(self, response_data, host, path, headers):
        """
        Process the response data before sending to the client
        """
        try:
            # Handle chunked encoding
            decoded_data, is_done = self._decode_chunked(bytes(response_data))
            # Handle gzip encoding
            decoded_data = self._decompress_zlib_stream(decoded_data)
            result  = self.parse_response(decoded_data)
            result["done"] = is_done
            return result
        except Exception as e:
            raise e

    def parse_response(self, response_data):
        pattern = rb'\[\[\[null,.*?]],"model"]'
        matches = []
        for match_obj in re.finditer(pattern, response_data):
            matches.append(match_obj.group(0))


        resp = {
            "reason": "",
            "body": "",
            "function": [],
        }

        # Print each full match
        for match in matches:
            json_data = json.loads(match)

            try:
                payload = json_data[0][0]
            except Exception as e:
                continue

            if len(payload)==2: # body
                resp["body"] = resp["body"] + payload[1]
            elif len(payload) == 11 and payload[1] is None and type(payload[10]) == list:  # function
                array_tool_calls = payload[10]
                func_name = array_tool_calls[0]
                params = self.parse_toolcall_params(array_tool_calls[1])
                resp["function"].append({"name":func_name, "params":params})
            elif len(payload) > 2: # reason
                resp["reason"] = resp["reason"] + payload[1]

        return resp

    def parse_toolcall_params(self, args):
        try:
            params = args[0]
            func_params = {}
            for param in params:
                param_name = param[0]
                param_value = param[1]

                if type(param_value)==list:
                    if len(param_value)==1: # null
                        func_params[param_name] = None
                    elif len(param_value) == 2: # number and integer
                        func_params[param_name] = param_value[1]
                    elif len(param_value) == 3: # string
                        func_params[param_name] = param_value[2]
                    elif len(param_value) == 4: # boolean
                        func_params[param_name] = param_value[3] == 1
                    elif len(param_value) == 5: # object
                        func_params[param_name] = self.parse_toolcall_params(param_value[4])
            return func_params
        except Exception as e:
            raise e

    @staticmethod
    def _decompress_zlib_stream(compressed_stream):
        decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 32)  # zlib header
        decompressed = decompressor.decompress(compressed_stream)
        return decompressed

    @staticmethod
    def _decode_chunked(response_body: bytes) -> tuple[bytes, bool]:
        chunked_data = bytearray()
        while True:
            # print(' '.join(format(x, '02x') for x in response_body))

            length_crlf_idx = response_body.find(b"\r\n")
            if length_crlf_idx == -1:
                break

            hex_length = response_body[:length_crlf_idx]
            try:
                length = int(hex_length, 16)
            except ValueError as e:
                logging.error(f"Parsing chunked length failed: {e}")
                break

            if length == 0:
                length_crlf_idx = response_body.find(b"0\r\n\r\n")
                if length_crlf_idx != -1:
                    return chunked_data, True

            if length + 2 > len(response_body):
                break

            chunked_data.extend(response_body[length_crlf_idx + 2:length_crlf_idx + 2 + length])
            if length_crlf_idx + 2 + length + 2 > len(response_body):
                break

            response_body = response_body[length_crlf_idx + 2 + length + 2:]
        return chunked_data, False
