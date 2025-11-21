import asyncio
from typing import Optional
import json
import logging
import ssl
import multiprocessing
from pathlib import Path

from stream.cert_manager import CertificateManager
from stream.proxy_connector import ProxyConnector
from stream.interceptors import HttpInterceptor

class ProxyServer:
    """
    Asynchronous HTTPS proxy server with SSL inspection capabilities
    """
    def __init__(self, host='0.0.0.0', port=3120, intercept_domains=None, upstream_proxy=None, queue: Optional[multiprocessing.Queue]=None):
        self.host = host
        self.port = port
        self.intercept_domains = intercept_domains or []
        self.passthrough_domains = [
            "feedback-pa.clients6.google.com",
            "play.google.com",
            "apis.google.com",
            "accounts.google.com"
        ]
        self.upstream_proxy = upstream_proxy
        self.queue = queue
        
        # Initialize components
        self.cert_manager = CertificateManager()
        self.proxy_connector = ProxyConnector(upstream_proxy)
        
        # Create logs directory
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        self.interceptor = HttpInterceptor(str(log_dir))
        
        # Set up logging
        self.logger = logging.getLogger('proxy_server')

        # Keep track of background tasks to prevent them from being destroyed prematurely
        self.background_tasks = set()
    
    def should_intercept(self, host):
        """
        Determine if the connection to the host should be intercepted
        """
        # Check passthrough domains first
        if host in self.passthrough_domains:
            return False

        if host in self.intercept_domains:
            return True

        # Wildcard match (e.g. *.example.com)
        for d in self.intercept_domains:
            if d.startswith("*."):
                suffix = d[1:]  # Remove *
                if host.endswith(suffix):
                    return True

        return False

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Handle a client connection
        """
        # Track this task to prevent "Task was destroyed but it is pending" errors
        current_task = asyncio.current_task()
        if current_task:
            self.background_tasks.add(current_task)
            current_task.add_done_callback(self.background_tasks.discard)

        try:
            # Read the initial request line
            request_line = await reader.readline()
            request_line = request_line.decode('utf-8').strip()
            
            if not request_line:
                writer.close()
                return
            
            # Parse the request line
            method, target, version = request_line.split(' ')
            
            if method == 'CONNECT':
                # Handle HTTPS connection
                await self._handle_connect(reader, writer, target)

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            writer.close()
    
    async def _handle_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target: str):
        """
        Handle CONNECT method (for HTTPS connections)
        """

        host, port = target.split(':')
        port = int(port)
        # Determine if we should intercept this connection
        intercept = self.should_intercept(host)

        if intercept:
            self.logger.info(f"Sniff HTTPS requests to : {target}")

            self.cert_manager.get_domain_cert(host)

            # Send 200 Connection Established to the client
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            await writer.drain()

            # Drop the proxy connect header
            await reader.read(8192)

            loop = asyncio.get_running_loop()
            transport = writer.transport # This is the original client transport

            if transport is None:
                self.logger.warning(f"Client writer transport is None for {host}:{port} before TLS upgrade. Closing.")
                return

            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(
                certfile=self.cert_manager.cert_dir / f"{host}.crt",
                keyfile=self.cert_manager.cert_dir / f"{host}.key"
            )

            client_protocol = transport.get_protocol()

            new_transport = await loop.start_tls(
                transport=transport,
                protocol=client_protocol,
                sslcontext=ssl_context,
                server_side=True
            )

            if new_transport is None:
                self.logger.error(f"loop.start_tls returned None for {host}:{port}, which is unexpected. Closing connection.")
                writer.close()
                return
            
            client_reader = reader

            client_writer = asyncio.StreamWriter(
                transport=new_transport,
                protocol=client_protocol,
                reader=client_reader,
                loop=loop
            )

            # Connect to the target server
            try:
                server_reader, server_writer = await self.proxy_connector.create_connection(
                    host, port, ssl=ssl.create_default_context()
                )
                
                # Start bidirectional forwarding with interception
                await self._forward_data_with_interception(
                    client_reader, client_writer,
                    server_reader, server_writer,
                    host
                )
            except Exception as e:
                # --- FIX: Log the unused exception variable ---
                self.logger.error(f"Error connecting to server {host}:{port}: {e}")
                client_writer.close()
        else:
            # No interception, just forward the connection
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            await writer.drain()

            # Drop the proxy connect header
            await reader.read(8192)

            try:
                # Connect to the target server
                server_reader, server_writer = await self.proxy_connector.create_connection(
                    host, port, ssl=None
                )

                # Start bidirectional forwarding without interception
                await self._forward_data(
                    reader, writer,
                    server_reader, server_writer
                )
            except Exception as e:
                # --- FIX: Log the unused exception variable ---
                self.logger.error(f"Error connecting to server {host}:{port}: {e}")
                writer.close()

    async def _forward_data(self, client_reader, client_writer, server_reader, server_writer):
        """
        Forward data between client and server without interception
        """
        async def _forward(reader, writer):
            try:
                while True:
                    data = await reader.read(8192)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except ConnectionResetError:
                self.logger.debug("Connection reset by peer.")
            except Exception as e:
                if getattr(e, 'winerror', None) == 10054:
                    self.logger.debug("Connection reset by peer (WinError 10054).")
                elif isinstance(e, ssl.SSLError) and "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in str(e):
                    self.logger.debug("Connection closed by peer (SSL notify)")
                    return
                else:
                    self.logger.error(f"Error forwarding data: {e}")
            finally:
                writer.close()
        
        # Create tasks for both directions
        client_to_server = asyncio.create_task(_forward(client_reader, server_writer))
        server_to_client = asyncio.create_task(_forward(server_reader, client_writer))
        
        # Wait for both tasks to complete
        tasks = [client_to_server, server_to_client]
        await asyncio.gather(*tasks)
    
    async def _forward_data_with_interception(self, client_reader, client_writer, 
                                             server_reader, server_writer, host):
        """
        Forward data between client and server with interception
        """
        # Buffer to store HTTP request/response data
        client_buffer = bytearray()
        server_buffer = bytearray()
        should_sniff = False

        # Parse HTTP headers from client
        async def _process_client_data():
            nonlocal client_buffer, should_sniff
            
            try:
                while True:
                    data = await client_reader.read(8192)
                    if not data:
                        break
                    client_buffer.extend(data)
                    
                    # Try to parse HTTP request
                    if b'\r\n\r\n' in client_buffer:
                        # Split headers and body
                        headers_end = client_buffer.find(b'\r\n\r\n') + 4
                        headers_data = client_buffer[:headers_end]
                        body_data = client_buffer[headers_end:]
                        
                        # Parse request line and headers
                        lines = headers_data.split(b'\r\n')
                        request_line = lines[0].decode('utf-8')
                        
                        try:
                            method, path, _ = request_line.split(' ')
                        except ValueError:
                            # Not a valid HTTP request, just forward
                            server_writer.write(client_buffer)
                            await server_writer.drain()
                            client_buffer.clear()
                            continue
                        
                        # Check if we should intercept this request
                        if 'GenerateContent' in path:
                            should_sniff = True
                            # Process the request body
                            processed_body = await self.interceptor.process_request(
                                body_data, host, path
                            )
                            
                            # Send the processed request
                            server_writer.write(headers_data)
                            server_writer.write(processed_body)
                        else:
                            should_sniff = False
                            # Forward the request as is
                            server_writer.write(client_buffer)
                        
                        await server_writer.drain()
                        client_buffer.clear()
                    else:
                        # Not enough data to parse headers, forward as is
                        server_writer.write(data)
                        await server_writer.drain()
                        client_buffer.clear()
            except ConnectionResetError:
                self.logger.debug("Connection reset by peer processing client data.")
            except Exception as e:
                if getattr(e, 'winerror', None) == 10054:
                    self.logger.debug("Connection reset by peer (WinError 10054) processing client data.")
                elif isinstance(e, ssl.SSLError) and "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in str(e):
                    self.logger.debug("Connection closed by peer (SSL notify) processing client data")
                    return
                else:
                    self.logger.error(f"Error processing client data: {e}")
            finally:
                server_writer.close()
        
        # Parse HTTP headers from server
        async def _process_server_data():
            nonlocal server_buffer, should_sniff
            
            try:
                while True:
                    data = await server_reader.read(8192)
                    if not data:
                        break

                    server_buffer.extend(data)
                    if b'\r\n\r\n' in server_buffer:
                        # Split headers and body
                        headers_end = server_buffer.find(b'\r\n\r\n') + 4
                        headers_data = server_buffer[:headers_end]
                        body_data = server_buffer[headers_end:]

                        # Parse status line and headers
                        lines = headers_data.split(b'\r\n')

                        # Parse headers
                        headers = {}
                        for i in range(1, len(lines)):
                            if not lines[i]:
                                continue
                            try:
                                key, value = lines[i].decode('utf-8').split(':', 1)
                                headers[key.strip()] = value.strip()
                            except ValueError:
                                continue

                        # Check if this is a response to a GenerateContent request
                        if should_sniff:
                            try:
                                resp = await self.interceptor.process_response(
                                    body_data, host, "", headers
                                )

                                if self.queue is not None:
                                    self.queue.put(json.dumps(resp))
                            except Exception as e:
                                # --- FIX: Log the unused exception variable ---
                                self.logger.error(f"Error during response interception: {e}")

                    # Not enough data to parse headers, forward as is
                    client_writer.write(data)
                    if b"0\r\n\r\n" in server_buffer:
                        server_buffer.clear()
            except ConnectionResetError:
                self.logger.debug("Connection reset by peer processing server data.")
            except Exception as e:
                if getattr(e, 'winerror', None) == 10054:
                    self.logger.debug("Connection reset by peer (WinError 10054) processing server data.")
                elif isinstance(e, ssl.SSLError) and "APPLICATION_DATA_AFTER_CLOSE_NOTIFY" in str(e):
                    self.logger.debug("Connection closed by peer (SSL notify) processing server data")
                    return
                else:
                    self.logger.error(f"Error processing server data: {e}")
            finally:
                client_writer.close()
        
        # Create tasks for both directions
        client_to_server = asyncio.create_task(_process_client_data())
        server_to_client = asyncio.create_task(_process_server_data())


        # Wait for both tasks to complete
        tasks = [client_to_server, server_to_client]
        await asyncio.gather(*tasks)
    
    async def start(self):
        """
        Start the proxy server
        """
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        
        addr = server.sockets[0].getsockname()
        self.logger.info(f'Serving on {addr}')
        
        # --- FIX: Send "READY" signal after server starts listening ---
        if self.queue:
            try:
                self.queue.put("READY")
                self.logger.info("Sent 'READY' signal to the main process.")
            except Exception as e:
                self.logger.error(f"Failed to send 'READY' signal: {e}")

        async with server:
            await server.serve_forever()