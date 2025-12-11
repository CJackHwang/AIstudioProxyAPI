// server.cjs (优化版 v2.17 - 增加日志ID & 常量)

const express = require('express');
const fs = require('fs');
const path = require('path');
const cors = require('cors');

// --- 依赖检查 ---
let playwright, expect;
const requiredModules = ['express', 'playwright', '@playwright/test', 'cors'];
const missingModules = [];

for (const modName of requiredModules) {
    try {
        if (modName === 'playwright') {
            playwright = require(modName);
        } else if (modName === '@playwright/test') {
            expect = require(modName).expect;
        } else {
            require(modName);
        }
        // console.log(`✅ 模块 ${modName} 已加载。`); // Optional: Log success
    } catch (e) {
        console.error(`❌ 模块 ${modName} 未找到。`);
        missingModules.push(modName);
    }
}

if (missingModules.length > 0) {
    console.error("-------------------------------------------------------------");
    console.error("❌ 错误：缺少必要的依赖模块！");
    console.error("请根据您使用的包管理器运行以下命令安装依赖：");
    console.error("-------------------------------------------------------------");
    console.error(`   npm install ${missingModules.join(' ')}`);
    console.error("   或");
    console.error(`   yarn add ${missingModules.join(' ')}`);
    console.error("   或");
    console.error(`   pnpm install ${missingModules.join(' ')}`);
    console.error("-------------------------------------------------------------");
    process.exit(1);
}

// --- 配置 ---
const SERVER_PORT = process.env.PORT || 2048;
const CHROME_DEBUGGING_PORT = 8848;
const CDP_ADDRESS = `http://127.0.0.1:${CHROME_DEBUGGING_PORT}`;
const AI_STUDIO_URL_PATTERN = 'aistudio.google.com/';
const RESPONSE_COMPLETION_TIMEOUT = 300000; // 5分钟总超时
const POLLING_INTERVAL = 300; // 非流式/通用检查间隔
const POLLING_INTERVAL_STREAM = 200; // 流式检查轮询间隔 (ms)
// v2.12: Timeout for secondary checks *after* spinner disappears
const POST_SPINNER_CHECK_DELAY_MS = 500; // Spinner消失后稍作等待再检查其他状态
const FINAL_STATE_CHECK_TIMEOUT_MS = 1500; // 检查按钮和输入框最终状态的超时
const SPINNER_CHECK_TIMEOUT_MS = 1000; // 检查Spinner状态的超时
const POST_COMPLETION_BUFFER = 1000; // JSON模式下可以缩短检查后等待时间
const SILENCE_TIMEOUT_MS = 1500; // 文本静默多久后认为稳定 (Spinner消失后)

// --- 常量 ---
const MODEL_NAME = 'google-ai-studio-via-playwright-cdp-json';
const CHAT_COMPLETION_ID_PREFIX = 'chatcmpl-';

// --- 选择器常量 ---
const INPUT_SELECTOR = 'ms-prompt-box textarea';
const SUBMIT_BUTTON_SELECTOR = 'button[aria-label="Run"]';
const RESPONSE_CONTAINER_SELECTOR = 'ms-chat-turn .chat-turn-container.model'; // 选择器指向 AI 模型回复的容器
const RESPONSE_TEXT_SELECTOR = 'ms-cmark-node.cmark-node';
const LOADING_SPINNER_SELECTOR = 'button[aria-label="Run"] svg .stoppable-spinner';
const ERROR_TOAST_SELECTOR = 'div.toast.warning, div.toast.error';
// !! 新增：清空聊天记录相关选择器 !!
const CLEAR_CHAT_BUTTON_SELECTOR = 'button[aria-label="Clear chat"][data-test-clear="outside"]:has(span.material-symbols-outlined:has-text("refresh"))'; // 清空按钮 (带图标确认)
const CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR = 'button.mdc-button:has-text("Continue")'; // 确认对话框中的 "Continue" 按钮
// !! 新增：清空验证相关常量 !!
const CLEAR_CHAT_VERIFY_TIMEOUT_MS = 5000; // 等待清空生效的总超时时间 (ms)
const CLEAR_CHAT_VERIFY_INTERVAL_MS = 300; // 检查清空状态的轮询间隔 (ms)

// v2.16: JSON Structure Prompt (Restored for non-streaming)
const prepareAIStudioPrompt = (userPrompt, systemPrompt = null) => {
    let fullPrompt = `
IMPORTANT: Your entire response MUST be a single JSON object. Do not include any text outside of this JSON object.
The JSON object must have a single key named "response".
Inside the value of the "response" key (which is a string), you MUST put the exact marker "<<<START_RESPONSE>>>"" at the very beginning of your actual answer. There should be NO text before this marker within the response string.
`;

    if (systemPrompt && systemPrompt.trim() !== '') {
        fullPrompt += `\nSystem Instruction: ${systemPrompt}\n`;
    }

    fullPrompt += `
Example 1:
User asks: "What is the capital of France?"
Your response MUST be:
{
  "response": "<<<START_RESPONSE>>>The capital of France is Paris."
}

Example 2:
User asks: "Write a python function to add two numbers"
Your response MUST be:
{
  "response": "<<<START_RESPONSE>>>\\\`\\\`\\\`python\\\\ndef add(a, b):\\\\n  return a + b\\\\n\\\`\\\`\\\`"
}

Now, answer the following user prompt, ensuring your output strictly adheres to the JSON format AND the start marker requirement described above:

User Prompt: "${userPrompt}"

Your JSON Response:
`;
    return fullPrompt;
};

// v2.26: Use JSON prompt for streaming as well -> vNEXT: Use Markdown Code Block for streaming
// vNEXT: Instruct AI to output *incomplete* JSON for streaming -> vNEXT: Instruct AI to output Markdown Code Block
const prepareAIStudioPromptStream = (userPrompt, systemPrompt = null) => {
    let fullPrompt = `
IMPORTANT: For this streaming request, your entire response MUST be enclosed in a single markdown code block (like \`\`\` block \`\`\`).
Inside this code block, your actual answer text MUST start immediately after the exact marker "<<<START_RESPONSE>>>".
Start your response exactly with "\`\`\`\n<<<START_RESPONSE>>>" followed by your answer content.
Continue outputting your answer content. You SHOULD include the final closing "\`\`\`" at the very end of your full response stream.
`;

    if (systemPrompt && systemPrompt.trim() !== '') {
        fullPrompt += `\nSystem Instruction: ${systemPrompt}\n`;
    }

    fullPrompt += `
Example 1 (Streaming):
User asks: "What is the capital of France?"
Your streamed response MUST look like this over time:
Stream part 1: \`\`\`\n<<<START_RESPONSE>>>The capital
Stream part 2:  of France is
Stream part 3:  Paris.\n\`\`\`

Example 2 (Streaming):
User asks: "Write a python function to add two numbers"
Your streamed response MUST look like this over time:
Stream part 1: \`\`\`\n<<<START_RESPONSE>>>\`\`\`python\ndef add(a, b):
Stream part 2: \n  return a + b\n
Stream part 3: \`\`\`\n\`\`\`

Now, answer the following user prompt, ensuring your output strictly adheres to the markdown code block, start marker, and streaming requirements described above:

User Prompt: "${userPrompt}"

Your Response (Streaming, within a markdown code block):
`;
    return fullPrompt;
};

const app = express();

// --- 全局变量 ---
let browser = null;
let page = null;
let isPlaywrightReady = false;
let isInitializing = false;
// v2.18: 请求队列和处理状态
let requestQueue = [];
let isProcessing = false;


// --- Playwright 初始化函数 ---
async function initializePlaywright() {
    if (isPlaywrightReady || isInitializing) return;
    isInitializing = true;
    console.log(`--- 初始化 Playwright: 连接到 ${CDP_ADDRESS} ---`);

    try {
        browser = await playwright.chromium.connectOverCDP(CDP_ADDRESS, { timeout: 20000, ignoreHTTPSErrors: true });
        console.log('✅ 成功连接到正在运行的 Chrome 实例！');

        browser.once('disconnected', () => {
            console.error('❌ Playwright 与 Chrome 的连接已断开！');
            isPlaywrightReady = false;
            browser = null;
            page = null;
            // v2.18: Clear queue on disconnect? Maybe not, let requests fail naturally.
        });

        await new Promise(resolve => setTimeout(resolve, 500));

        const contexts = browser.contexts();
        let context;
        if (!contexts || contexts.length === 0) {
             await new Promise(resolve => setTimeout(resolve, 1500));
             const retryContexts = browser.contexts();
             if (!retryContexts || retryContexts.length === 0) {
                 throw new Error('无法获取浏览器上下文。请检查 Chrome 是否已正确启动并响应。');
             }
             context = retryContexts[0];
        } else {
             context = contexts[0];
        }

        let foundPage = null;
        const pages = context.pages();
        console.log(`-> 发现 ${pages.length} 个页面。正在搜索 AI Studio (匹配 "${AI_STUDIO_URL_PATTERN}")...`);
        for (const p of pages) {
            try {
                 if (p.isClosed()) continue;
                const url = p.url();
                if (url.includes(AI_STUDIO_URL_PATTERN) && url.includes('/prompts/')) {
                    console.log(`-> 找到 AI Studio 页面: ${url}`);
                    foundPage = p;
                    break;
                }
            } catch (pageError) {
                 if (!p.isClosed()) {
                     console.warn(`   警告：评估页面 URL 时出错: ${pageError.message.split('\\n')[0]}`);
                 }
            }
        }

        if (!foundPage) {
            throw new Error(`未在已连接的 Chrome 中找到包含 "${AI_STUDIO_URL_PATTERN}" 和 "/prompts/" 的页面。请确保 auto_connect_aistudio.js 已成功运行，并且 AI Studio 页面 (例如 prompts/new_chat) 已打开。`);
        }

        page = foundPage;
        console.log('-> 已定位到 AI Studio 页面。');
        await page.bringToFront();
        console.log('-> 尝试将页面置于前台。检查加载状态...');
        await page.waitForLoadState('domcontentloaded', { timeout: 15000 });
        console.log('-> 页面 DOM 已加载。');

        try {
            console.log("-> 尝试定位核心输入区域以确认页面就绪...");
            await page.locator('ms-prompt-box').waitFor({ state: 'visible', timeout: 15000 });
             console.log("-> 核心输入区域容器已找到。");
        } catch(initCheckError) {
            console.warn(`⚠️ 初始化检查警告：未能快速定位到核心输入区域容器。页面可能仍在加载或结构有变: ${initCheckError.message.split('\\n')[0]}`);
            await saveErrorSnapshot('init_check_fail');
        }

        isPlaywrightReady = true;
        console.log('✅ Playwright 已准备就绪。');
        // v2.18: Start processing queue if playwright just became ready and queue has items
        if (requestQueue.length > 0 && !isProcessing) {
             console.log(`[Queue] Playwright 就绪，队列中有 ${requestQueue.length} 个请求，开始处理...`);
             processQueue();
        }

    } catch (error) {
        console.error(`❌ 初始化 Playwright 失败: ${error.message}`);
        await saveErrorSnapshot('init_fail');
        isPlaywrightReady = false;
        browser = null;
        page = null;
    } finally {
        isInitializing = false;
    }
}

// --- 中间件 ---
app.use(cors());
app.use(express.json({ limit: '20mb' }));
app.use(express.urlencoded({ limit: '20mb', extended: true })); // Also for urlencoded

// --- Web UI Route ---
app.get('/', (req, res) => {
    const htmlPath = path.join(__dirname, 'index.html');
    if (fs.existsSync(htmlPath)) {
        res.sendFile(htmlPath);
    } else {
        res.status(404).send('Error: index.html not found.');
    }
});

// --- 健康检查 ---
app.get('/health', (req, res) => {
    const isConnected = browser?.isConnected() ?? false;
    const isPageValid = page && !page.isClosed();
    const queueLength = requestQueue.length;
    const status = {
        status: 'Unknown',
        message: '',
        playwrightReady: isPlaywrightReady,
        browserConnected: isConnected,
        pageValid: isPageValid,
        initializing: isInitializing,
        processing: isProcessing,
        queueLength: queueLength
    };

    if (isPlaywrightReady && isPageValid && isConnected) {
        status.status = 'OK';
        status.message = `Server running, Playwright connected, page valid. Currently ${isProcessing ? 'processing' : 'idle'} with ${queueLength} item(s) in queue.`;
        res.status(200).json(status);
    } else {
        status.status = 'Error';
        const reasons = [];
        if (!isPlaywrightReady) reasons.push("Playwright not initialized or ready");
        if (!isPageValid) reasons.push("Target page not found or closed");
        if (!isConnected) reasons.push("Browser disconnected");
        if (isInitializing) reasons.push("Playwright is currently initializing");
        status.message = `Service Unavailable. Issues: ${reasons.join(', ')}. Currently ${isProcessing ? 'processing' : 'idle'} with ${queueLength} item(s) in queue.`;
        res.status(503).json(status);
    }
});

// --- 新增：API 辅助函数 ---

// 验证聊天请求
// v2.19: Updated validation to handle array content (text parts only)
function validateChatRequest(messages) {
    const reqId = messages?.[0]?.reqId || 'validation'; // Get reqId if passed, fallback
    if (!messages || !Array.isArray(messages) || messages.length === 0) {
        throw new Error(`[${reqId}] Invalid request: "messages" array is missing or empty.`);
    }
    const lastUserMessage = messages.filter(msg => msg.role === 'user').pop();
    if (!lastUserMessage) {
        throw new Error(`[${reqId}] Invalid request: No user message found in the "messages" array.`);
    }

    let userPromptContentInput = lastUserMessage.content;
    let processedUserPrompt = ""; // Initialize as empty string

    // 1. Handle null/undefined content
    if (userPromptContentInput === null || userPromptContentInput === undefined) {
        console.warn(`[${reqId}] (Validation) Warning: Last user message content is null or undefined. Treating as empty string.`);
        processedUserPrompt = "";
    }
    // 2. Handle string content (most common case)
    else if (typeof userPromptContentInput === 'string') {
        processedUserPrompt = userPromptContentInput;
    }
    // 3. Handle array content (attempt compatibility with OpenAI vision format)
    else if (Array.isArray(userPromptContentInput)) {
        console.log(`[${reqId}] (Validation) Info: Last user message content is an array. Processing text parts...`);
        let textParts = [];
        let unsupportedParts = false;
        for (const item of userPromptContentInput) {
            if (typeof item === 'object' && item !== null && item.type === 'text' && typeof item.text === 'string') {
                textParts.push(item.text);
            } else if (typeof item === 'object' && item !== null && item.type === 'image_url') {
                console.warn(`[${reqId}] (Validation) Warning: Found 'image_url' content part. This proxy cannot process images via AI Studio web UI. Ignoring image.`);
                unsupportedParts = true;
                // Optionally, include the URL as text, but it might confuse the AI:
                // textParts.push(`[Image URL (Unsupported): ${item.image_url?.url || 'N/A'}]`);
            } else {
                // Handle other unexpected items in the array - stringify them?
                 console.warn(`[${reqId}] (Validation) Warning: Found unexpected item in content array (Type: ${typeof item}). Converting to JSON string.`);
                 try {
                      textParts.push(JSON.stringify(item));
                      unsupportedParts = true;
                 } catch (e) {
                      console.error(`[${reqId}] (Validation) Error stringifying array item: ${e}. Skipping item.`);
                 }
            }
        }
        processedUserPrompt = textParts.join('\\n'); // Join text parts with newline
        if (unsupportedParts) {
             console.warn(`[${reqId}] (Validation) Warning: Some parts of the array content were unsupported or ignored (e.g., images). Only text parts were included in the final prompt.`);
        }
        if (!processedUserPrompt) {
             console.warn(`[${reqId}] (Validation) Warning: Processed array content resulted in an empty prompt.`);
        }
    }
    // 4. Handle other object types (fallback to JSON stringify)
    else if (typeof userPromptContentInput === 'object' && userPromptContentInput !== null) {
        console.warn(`[${reqId}] (Validation) Warning: Last user message content is an object but not a recognized array format. Converting to JSON string.`);
        try {
            processedUserPrompt = JSON.stringify(userPromptContentInput);
        } catch (stringifyError) {
            console.error(`[${reqId}] (Validation) Error stringifying object user content: ${stringifyError}. Falling back to empty string.`);
            processedUserPrompt = "";
        }
    }
    // 5. Handle other primitive types (e.g., number, boolean) - convert to string
    else {
        console.warn(`[${reqId}] (Validation) Warning: Last user message content is an unexpected primitive type (${typeof userPromptContentInput}). Converting to string.`);
        processedUserPrompt = String(userPromptContentInput);
    }

    // Final check - should always be a string here
    if (typeof processedUserPrompt !== 'string') {
         console.error(`[${reqId}] (Validation) CRITICAL ERROR: Failed to process user prompt content into a string. Type after processing: ${typeof processedUserPrompt}. Using empty string.`);
         processedUserPrompt = ""; // Safeguard
    }


    // Extract system prompt (remains the same logic)
    const systemPromptContent = messages.find(msg => msg.role === 'system')?.content;
    // Basic validation for system prompt (ensure it's a string if provided)
    let processedSystemPrompt = null;
    if (systemPromptContent !== null && systemPromptContent !== undefined) {
        if (typeof systemPromptContent === 'string') {
            processedSystemPrompt = systemPromptContent;
        } else {
            console.warn(`[${reqId}] (Validation) Warning: System prompt content is not a string (Type: ${typeof systemPromptContent}). Ignoring system prompt.`);
            // Optionally stringify it: processedSystemPrompt = JSON.stringify(systemPromptContent);
        }
    }


    return {
        userPrompt: processedUserPrompt, // Ensure this is always a string
        systemPrompt: processedSystemPrompt // Ensure this is null or a string
    };
}

// 与页面交互并提交 Prompt
async function interactAndSubmitPrompt(page, prompt, reqId) {
    console.log(`[${reqId}] 开始页面交互...`);
    const inputField = page.locator(INPUT_SELECTOR);
    const submitButton = page.locator(SUBMIT_BUTTON_SELECTOR);
    const loadingSpinner = page.locator(LOADING_SPINNER_SELECTOR); // Keep spinner locator here for later use

    console.log(`[${reqId}]  - 等待输入框可用...`);
        try {
            await inputField.waitFor({ state: 'visible', timeout: 10000 });
        } catch (e) {
         console.error(`[${reqId}] ❌ 查找输入框失败！`);
         await saveErrorSnapshot(`input_field_not_visible_${reqId}`);
         throw new Error(`[${reqId}] Failed to find visible input field. Error: ${e.message}`);
    }

    console.log(`[${reqId}]  - 清空并填充输入框...`);
        await inputField.fill(prompt, { timeout: 60000 });

    console.log(`[${reqId}]  - 等待运行按钮可用...`);
        try {
            await expect(submitButton).toBeEnabled({ timeout: 10000 });
        } catch (e) {
        console.error(`[${reqId}] ❌ 等待运行按钮变为可用状态超时！`);
        await saveErrorSnapshot(`submit_button_not_enabled_before_click_${reqId}`);
        throw new Error(`[${reqId}] Submit button not enabled before click. Error: ${e.message}`);
    }

    console.log(`[${reqId}]  - 点击运行按钮...`);
    await submitButton.click({ timeout: 10000 });

    return { inputField, submitButton, loadingSpinner }; // Return locators
}

// 定位最新的回复元素
async function locateResponseElements(page, { inputField, submitButton, loadingSpinner }, reqId) {
    console.log(`[${reqId}] 定位 AI 回复元素...`);
        let lastResponseContainer;
    let responseElement;
        let locatedResponseElements = false;

        for (let i = 0; i < 3 && !locatedResponseElements; i++) {
             try {
             console.log(`[${reqId}]    尝试定位最新回复容器及文本元素 (第 ${i + 1} 次)`);
                 await page.waitForTimeout(500 + i * 500); // 固有延迟

             const isEndState = await checkEndConditionQuickly(page, loadingSpinner, inputField, submitButton, 250, reqId);
             const locateTimeout = isEndState ? 3000 : 60000;
                 if (isEndState) {
                console.log(`[${reqId}]     -> 检测到结束条件已满足，使用 ${locateTimeout / 1000}s 超时进行定位。`);
                 }

             lastResponseContainer = page.locator(RESPONSE_CONTAINER_SELECTOR).last();
                 await lastResponseContainer.waitFor({ state: 'attached', timeout: locateTimeout });

             responseElement = lastResponseContainer.locator(RESPONSE_TEXT_SELECTOR);
                 await responseElement.waitFor({ state: 'attached', timeout: locateTimeout });

             console.log(`[${reqId}]    回复容器和文本元素定位成功。`);
                 locatedResponseElements = true;
             } catch (locateError) {
             console.warn(`[${reqId}]    第 ${i + 1} 次定位回复元素失败: ${locateError.message.split('\n')[0]}`);
                 if (i === 2) {
                  await saveErrorSnapshot(`response_locate_fail_${reqId}`);
                  throw new Error(`[${reqId}] Failed to locate response elements after multiple attempts.`);
             }
         }
    }
    if (!locatedResponseElements) throw new Error(`[${reqId}] Could not locate response elements.`);
    return { responseElement, lastResponseContainer }; // Return located elements
}

// --- 新增：处理流式响应 (vNEXT: 标记优先，静默结束，无JSON处理) ---
async function handleStreamingResponse(res, responseElement, page, { inputField, submitButton, loadingSpinner }, operationTimer, reqId, isRequestCancelled) {
    console.log(`[${reqId}]   - 流式传输开始 (vNEXT: Marker priority, silence end, no JSON handling)...`); // TODO: Update version
    let lastRawText = "";
    let lastSentResponseContent = ""; // Tracks content *after* the marker that has been SENT
    let responseStarted = false; // Tracks if <<<START_RESPONSE>>> has been seen
    const startTime = Date.now();
    let spinnerHasDisappeared = false;
    let lastTextChangeTimestamp = Date.now();
    const startMarker = '<<<START_RESPONSE>>>';
    let streamFinishedNaturally = false;

    while (Date.now() - startTime < RESPONSE_COMPLETION_TIMEOUT && !streamFinishedNaturally) {
        // --- 添加检查：请求是否已取消 ---
        const cancelled = isRequestCancelled(); // 调用检查函数
        // 添加日志记录检查结果
        // console.log(`[${reqId}]   (Streaming Loop Check) isRequestCancelled() returned: ${cancelled}`); // 可选：过于频繁，暂时注释掉
        if (cancelled) {
             console.log(`[${reqId}]   (Streaming) 检测到请求已取消 (isRequestCancelled() is true)，停止处理。`); // 修改日志
             clearTimeout(operationTimer); // 确保定时器清除
             if (!res.writableEnded) res.end(); // 确保响应结束
             return; // 退出函数
        }
        // --- 结束检查 ---

        const loopStartTime = Date.now();

        // 1. Get current raw text
        const currentRawText = await getRawTextContent(responseElement, lastRawText, reqId);

        if (currentRawText !== lastRawText) {
            lastTextChangeTimestamp = Date.now();
            let potentialNewDelta = "";
            let currentContentAfterMarker = "";

            // 2. Marker Check & Delta Calculation
            const markerIndex = currentRawText.indexOf(startMarker);
            if (markerIndex !== -1) {
                if (!responseStarted) {
                    console.log(`[${reqId}]    (流式 Simple) 检测到 ${startMarker}，开始传输...`);
                    responseStarted = true;
                }
                // Content after marker in the current raw text
                currentContentAfterMarker = currentRawText.substring(markerIndex + startMarker.length);
                // Calculate new content since last *sent* content
                potentialNewDelta = currentContentAfterMarker.substring(lastSentResponseContent.length);
            } else if(responseStarted) {
                 // If marker was seen before, but now disappears (e.g., AI cleared output?), treat as no new delta.
                 potentialNewDelta = "";
                 console.warn(`[${reqId}] Marker disappeared after being seen. Raw: ${currentRawText.substring(0,100)}`);
            }

            // 3. Send Delta if found
            if (potentialNewDelta) {
                 // console.log(`[${reqId}]    (Send Stream Simple) Sending Delta (len: ${potentialNewDelta.length})`);
                 sendStreamChunk(res, potentialNewDelta, reqId);
                 lastSentResponseContent += potentialNewDelta; // Update tracking
            }

            // Update last raw text
            lastRawText = currentRawText;

        } // End if(currentRawText !== lastRawText)

        // 4. Check Spinner status
        if (!spinnerHasDisappeared) {
            try {
                await expect(loadingSpinner).toBeHidden({ timeout: 50 });
                spinnerHasDisappeared = true;
                lastTextChangeTimestamp = Date.now(); // Reset silence timer when spinner disappears
                console.log(`[${reqId}]    Spinner 已消失，进入静默期检测...`);
            } catch (e) { /* Spinner still visible */ }
        }

        // 5. Silence Check (Standard)
        const isSilent = spinnerHasDisappeared && (Date.now() - lastTextChangeTimestamp > SILENCE_TIMEOUT_MS);

        if (isSilent) {
            console.log(`[${reqId}] Silence detected. Finishing stream.`);
            streamFinishedNaturally = true;
            break; // Exit loop
        }

        // 6. Control polling interval
        const loopEndTime = Date.now();
        const loopDuration = loopEndTime - loopStartTime;
        const waitTime = Math.max(0, POLLING_INTERVAL_STREAM - loopDuration);
        await page.waitForTimeout(waitTime);

    } // --- End main loop ---

    // --- Cleanup and End --- (如果循环是因取消而退出，下面的代码不会执行)
    clearTimeout(operationTimer); // Clear the specific timer for THIS request

    if (!streamFinishedNaturally && Date.now() - startTime >= RESPONSE_COMPLETION_TIMEOUT) {
        // Timeout case
        console.warn(`[${reqId}]   - 流式传输(Simple模式)因总超时 (${RESPONSE_COMPLETION_TIMEOUT / 1000}s) 结束。`);
        await saveErrorSnapshot(`streaming_simple_timeout_${reqId}`);
        if (!res.writableEnded) {
            sendStreamError(res, "Stream processing timed out on server (Simple mode).", reqId);
        }
    } else if (streamFinishedNaturally && !res.writableEnded) {
        // Natural end (Silence detected)
        // --- Final Sync (Simple Mode) ---
        // Check one last time for any content received after the last delta was sent but before silence was declared.
        console.log(`[${reqId}]    (Simple Stream) Loop ended naturally, performing final sync check...`);
        const finalRawText = await getRawTextContent(responseElement, lastRawText, reqId);
        console.log(`[${reqId}]    (Simple Stream) Performing final marker check and delta calculation...`);
        try {
             let finalExtractedContent = ""; // Content after marker
             const finalMarkerIndex = finalRawText.indexOf(startMarker);
             if (finalMarkerIndex !== -1) {
                  finalExtractedContent = finalRawText.substring(finalMarkerIndex + startMarker.length);
             }

             const finalDelta = finalExtractedContent.substring(lastSentResponseContent.length);

            if (finalDelta){
                 console.log(`[${reqId}]    (Final Sync Simple) Sending final delta (len: ${finalDelta.length})`);
                 sendStreamChunk(res, finalDelta, reqId);
            } else {
                 console.log(`[${reqId}]    (Final Sync Simple) No final delta to send based on lastSent comparison.`);
            }
        } catch (e) { console.warn(`[${reqId}] (Simple Stream) Final sync error during marker/delta calc: ${e.message}`); }
        // --- End Final Sync ---

        res.write('data: [DONE]\n\n');
        res.end();
        console.log(`[${reqId}] ✅ 流式(Simple模式)响应 [DONE] 已发送。`);
    } else if (res.writableEnded) {
        console.log(`[${reqId}] 流(Simple模式)已提前结束 (writableEnded=true)，不再发送 [DONE]。`);
    } else {
         console.log(`[${reqId}] 流(Simple模式)结束时状态异常 (finishedNaturally=${streamFinishedNaturally}, writableEnded=${res.writableEnded})，不再发送 [DONE]。`);
    }
}

// --- 新增：处理非流式响应 --- vNEXT: Restore JSON Parsing
async function handleNonStreamingResponse(res, page, locators, operationTimer, reqId, isRequestCancelled) {
    console.log(`[${reqId}]   - 等待 AI 处理完成 (检查 Spinner 消失 + 输入框空 + 按钮禁用)...`);
            let processComplete = false;
            const nonStreamStartTime = Date.now();
    let finalStateCheckInitiated = false;
    const { inputField, submitButton, loadingSpinner } = locators;

    // Completion check logic
            while (!processComplete && Date.now() - nonStreamStartTime < RESPONSE_COMPLETION_TIMEOUT) {
                // --- 添加检查：请求是否已取消 ---
                if (isRequestCancelled()) {
                    console.log(`[${reqId}]   (Non-Streaming) 检测到请求已取消，停止等待完成状态。`);
                    clearTimeout(operationTimer); // 确保定时器清除
                    if (!res.headersSent) {
                         // 如果头还没发送，可以发送一个取消错误
                         res.status(499).json({ error: { message: `[${reqId}] Client closed request`, type: 'client_error' } });
                    } else if (!res.writableEnded) {
                         res.end(); // 否则只结束响应
                    }
                    return; // 退出函数
                }
                // --- 结束检查 ---

                  let isSpinnerHidden = false;
                  let isInputEmpty = false;
                  let isButtonDisabled = false;

                  try {
                      await expect(loadingSpinner).toBeHidden({ timeout: SPINNER_CHECK_TIMEOUT_MS });
                      isSpinnerHidden = true;
                  } catch { /* Spinner still visible */ }

                  if (isSpinnerHidden) {
                      try {
                          await expect(inputField).toHaveValue('', { timeout: FINAL_STATE_CHECK_TIMEOUT_MS });
                          isInputEmpty = true;
                      } catch { /* Input not empty */ }

                      if (isInputEmpty) {
                          try {
                              await expect(submitButton).toBeDisabled({ timeout: FINAL_STATE_CHECK_TIMEOUT_MS });
                              isButtonDisabled = true;
                          } catch { /* Button not disabled */ }
                      }
                  }

                  if (isSpinnerHidden && isInputEmpty && isButtonDisabled) {
                      if (!finalStateCheckInitiated) {
                          finalStateCheckInitiated = true;
                console.log(`[${reqId}]    检测到潜在最终状态。等待 ${POST_COMPLETION_BUFFER}ms 进行确认...`); // Use constant
                await page.waitForTimeout(POST_COMPLETION_BUFFER); // Wait a bit first
                console.log(`[${reqId}]    ${POST_COMPLETION_BUFFER}ms 等待结束，重新检查状态...`);
                try {
                    await expect(loadingSpinner).toBeHidden({ timeout: 500 });
                    await expect(inputField).toHaveValue('', { timeout: 500 });
                    await expect(submitButton).toBeDisabled({ timeout: 500 });
                    console.log(`[${reqId}]    状态确认成功。开始文本静默检查...`);

                    // --- NEW: Text Silence Check ---
                    let lastCheckText = '';
                    let currentCheckText = '';
                    let textStable = false;
                    const silenceCheckStartTime = Date.now();
                    // Re-locate response element here for the check
                    const { responseElement: checkResponseElement } = await locateResponseElements(page, locators, reqId);

                    while (Date.now() - silenceCheckStartTime < SILENCE_TIMEOUT_MS * 2) { // Check for up to 2*silence duration
                        lastCheckText = currentCheckText;
                        currentCheckText = await getRawTextContent(checkResponseElement, lastCheckText, reqId);
                        if (currentCheckText === lastCheckText) {
                             // Text hasn't changed since last check in this loop
                             if (Date.now() - silenceCheckStartTime >= SILENCE_TIMEOUT_MS) {
                                  // And enough time has passed
                                  console.log(`[${reqId}]    文本内容静默 ${SILENCE_TIMEOUT_MS}ms，确认处理完成。`);
                                  textStable = true;
                                  break;
                             }
                        } else {
                            // Text changed, reset silence timer within this check
                            // silenceCheckStartTime = Date.now(); // Option: Reset timer on any change
                            console.log(`[${reqId}]    (静默检查) 文本仍在变化...`);
                        }
                        await page.waitForTimeout(POLLING_INTERVAL); // Use standard poll interval for checks
                    }

                    if (textStable) {
                         processComplete = true; // Mark process as complete
                    } else {
                         console.warn(`[${reqId}]    警告: 文本静默检查超时，可能仍在输出。将继续尝试解析。`);
                         processComplete = true; // Proceed anyway after timeout, but log warning
                    }
                    // --- END NEW: Text Silence Check ---

                } catch (recheckError) {
                    console.log(`[${reqId}]    状态在确认期间发生变化 (${recheckError.message.split('\\n')[0]})。继续轮询...`);
                    finalStateCheckInitiated = false;
                }
            }
        } else {
             if (finalStateCheckInitiated) {
                 console.log(`[${reqId}]    最终状态不再满足，重置确认标志。`);
                 finalStateCheckInitiated = false;
             }
             await page.waitForTimeout(POLLING_INTERVAL * 2); // Longer wait if not in final state check
        }
    } // --- End Completion check logic loop ---

    // --- 添加检查：如果在循环结束后发现请求已取消 ---
    if (isRequestCancelled()) {
        console.log(`[${reqId}]   (Non-Streaming) 请求在等待完成后被取消，不再继续处理。`);
        // 定时器和响应应该已经被上面的检查处理了，这里只退出
        return;
    }
    // --- 结束检查 ---

    // Check for Page Errors BEFORE attempting to parse JSON
    console.log(`[${reqId}]   - 检查页面上是否存在错误提示...`);
    const pageError = await detectAndExtractPageError(page, reqId);
              if (pageError) {
        console.error(`[${reqId}] ❌ 检测到 AI Studio 页面错误: ${pageError}`);
        await saveErrorSnapshot(`page_error_detected_${reqId}`);
        throw new Error(`[${reqId}] AI Studio Error: ${pageError}`);
              }

              if (!processComplete) {
         console.warn(`[${reqId}]    警告：等待最终完成状态超时或未能稳定确认 (${(Date.now() - nonStreamStartTime) / 1000}s)。将直接尝试获取并解析JSON。`);
          await saveErrorSnapshot(`nonstream_final_state_timeout_${reqId}`);
               } else {
         console.log(`[${reqId}]   - 开始获取并解析最终 JSON...`);
               }

    // Get and Parse JSON
             let aiResponseText = null;
             const maxRetries = 3;
             let attempts = 0;

             while (attempts < maxRetries && aiResponseText === null) {
                  attempts++;
         console.log(`[${reqId}]     - 尝试获取原始文本并解析 JSON (第 ${attempts} 次)...`);
         try {
             // Re-locate response element within the retry loop for robustness
             const { responseElement: currentResponseElement } = await locateResponseElements(page, locators, reqId);

             const rawText = await getRawTextContent(currentResponseElement, '', reqId);

                      if (!rawText || rawText.trim() === '') {
                 console.warn(`[${reqId}]     - 第 ${attempts} 次获取的原始文本为空。`);
                          throw new Error("Raw text content is empty.");
                      }
              console.log(`[${reqId}]     - 获取到原始文本 (长度: ${rawText.length}): \"${rawText.substring(0,100)}...\"`);

             const parsedJson = tryParseJson(rawText, reqId);

                      if (parsedJson) {
                          if (typeof parsedJson.response === 'string') {
                              aiResponseText = parsedJson.response;
                              console.log(`[${reqId}]     - 成功解析 JSON 并提取 'response' 字段。`);
                          } else {
                              // JSON 有效但无 response 字段
                              try {
                                  aiResponseText = JSON.stringify(parsedJson);
                                  console.log(`[${reqId}]     - 警告: 未找到 'response' 字段，但解析到有效 JSON。将整个 JSON 字符串化作为回复。`);
                              } catch (stringifyError) {
                                  console.error(`[${reqId}]     - 错误：无法将解析出的 JSON 字符串化: ${stringifyError.message}`);
                                  aiResponseText = null;
                                  throw new Error("Failed to stringify the parsed JSON object.");
                              }
                          }
                      } else {
                          // JSON 解析失败
                          console.warn(`[${reqId}]     - 第 ${attempts} 次未能解析 JSON。`);
                          aiResponseText = null;
                          if (attempts >= maxRetries) {
                              await saveErrorSnapshot(`json_parse_fail_final_attempt_${reqId}`);
                          }
                          throw new Error("Failed to parse JSON from raw text.");
                      }

                 break;

                  } catch (e) {
             console.warn(`[${reqId}]     - 第 ${attempts} 次获取或解析失败: ${e.message.split('\n')[0]}`);
             aiResponseText = null;
                      if (attempts >= maxRetries) {
                 console.error(`[${reqId}]     - 多次尝试获取并解析 JSON 失败。`);
                 if (!e.message?.includes('snapshot')) await saveErrorSnapshot(`get_parse_json_failed_final_${reqId}`);
                          aiResponseText = ""; // Fallback to empty string
                      } else {
                  await new Promise(resolve => setTimeout(resolve, 1500 + attempts * 500));
                      }
                  }
             }

            if (aiResponseText === null) {
         console.log(`[${reqId}]     - JSON 解析失败，再次检查页面错误...`);
         const finalCheckError = await detectAndExtractPageError(page, reqId);
                 if (finalCheckError) {
              console.error(`[${reqId}] ❌ 检测到 AI Studio 页面错误 (在 JSON 解析失败后): ${finalCheckError}`);
              await saveErrorSnapshot(`page_error_post_json_fail_${reqId}`);
              throw new Error(`[${reqId}] AI Studio Error after JSON parse failed: ${finalCheckError}`);
         }
          console.warn(`[${reqId}] 警告：所有尝试均未能获取并解析出有效的 JSON 回复。返回空回复。`);
                  aiResponseText = "";
              }

    // Handle potential nested JSON
            let cleanedResponse = aiResponseText;
            try {
                 // Attempt to parse the potential stringified JSON again for nested 'response' check
                 // Only attempt if aiResponseText is likely a stringified JSON object/array
                 if (aiResponseText && aiResponseText.startsWith('{') || aiResponseText.startsWith('[')) {
                      const outerParsed = JSON.parse(aiResponseText); // Use JSON.parse directly here
                      const innerParsed = tryParseJson(outerParsed.response, reqId); // Try parsing the inner 'response' field if it exists
                      if (innerParsed && typeof innerParsed.response === 'string') {
                          console.log(`[${reqId}]    (非流式) 检测到嵌套 JSON，使用内层 response 内容。`);
                          cleanedResponse = innerParsed.response;
                      } else if (typeof outerParsed.response === 'string') {
                          // If the *outer* 'response' was already a string (not nested JSON), use it directly
                          console.log(`[${reqId}]    (非流式) 使用外层 'response' 字段内容。`);
                          cleanedResponse = outerParsed.response;
                      }
                      // If neither inner nor outer 'response' fields are relevant strings, keep the stringified JSON as cleanedResponse
                 }
            } catch (e) {
                 // If parsing aiResponseText fails, it means it wasn't a stringified JSON in the first place,
                 // or it was malformed. Keep the original aiResponseText.
                 // console.warn(`[${reqId}] (Info) Post-processing check: aiResponseText ('${aiResponseText.substring(0,50)}...') is not a parseable JSON or lacks 'response'. Keeping original value. Error: ${e.message}`);
                 cleanedResponse = aiResponseText; // Keep original if parsing fails
            }

    console.log(`[${reqId}] ✅ 获取到解析后的 AI 回复 (来自JSON, 长度: ${cleanedResponse?.length ?? 0}): \"${cleanedResponse?.substring(0, 100)}...\"`);

               // --- 新增步骤：在非流式响应中移除标记 ---
               const startMarker = '<<<START_RESPONSE>>>';

               let finalContentForUser = cleanedResponse; // 默认使用清理后的响应

               // Check for and remove the starting marker if present
               if (finalContentForUser?.startsWith(startMarker)) {
                    finalContentForUser = finalContentForUser.substring(startMarker.length);
                    console.log(`[${reqId}]    (非流式 JSON) 移除前缀 ${startMarker}，最终内容长度: ${finalContentForUser.length}`);
               } else if (aiResponseText !== null && aiResponseText !== "") { // 仅在获取到非空文本但无标记时警告
                    console.warn(`[${reqId}]    (非流式 JSON) 警告: 未在 response 字段中找到预期的 ${startMarker} 前缀。内容: \"${aiResponseText.substring(0,50)}...\"`);
               }
               // --- 结束新增步骤 ---


               // 使用移除标记后的内容构建最终响应
               const responsePayload = {
                  id: `${CHAT_COMPLETION_ID_PREFIX}${Date.now()}-${Math.random().toString(36).substring(2, 15)}`,
                  object: 'chat.completion',
                  created: Math.floor(Date.now() / 1000),
                  model: MODEL_NAME,
                  choices: [{
                      index: 0,
                      message: { role: 'assistant', content: finalContentForUser }, // Use cleaned content
                      finish_reason: 'stop',
                  }],
                  usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
              };
              console.log(`[${reqId}] ✅ 返回 JSON 响应 (来自解析后的JSON)。`);
              clearTimeout(operationTimer); // Clear the specific timer for THIS request
              res.json(responsePayload);
          }

// --- 新增：处理 /v1/models 请求以满足 Open WebUI 验证 ---
app.get('/v1/models', (req, res) => {
    const modelId = 'aistudio-proxy'; // 您计划在 Open WebUI 中使用的模型名称
    // 使用简短的日志ID或时间戳
    const logPrefix = `[${Date.now().toString(36).slice(-5)}]`;
    console.log(`${logPrefix} --- 收到 /v1/models 请求，返回模拟模型列表 ---`);
    res.json({
        object: "list",
        data: [
            {
                id: modelId, // 返回您要用的那个名字
                object: "model",
                created: Math.floor(Date.now() / 1000),
                owned_by: "openai-proxy", // 可以随便写
                permission: [],
                root: modelId,
                parent: null
            }
            // 如果需要添加更多名称指向同一个代理，可以在此添加
            // ,{
            //    id: "gemini-pro-proxy",
            //    object: "model",
            //    created: Math.floor(Date.now() / 1000),
            //    owned_by: "openai-proxy",
            //    permission: [],
            //    root: "gemini-pro-proxy",
            //    parent: null
            // }
        ]
    });
});


// --- v2.18: 新增队列处理函数 ---
async function processQueue() {
     if (isProcessing || requestQueue.length === 0) {
          return;
     }

     isProcessing = true;
     // 从队列头部取出包含状态的请求项
     const queueItem = requestQueue.shift();
     // 解构所需变量，包括取消标记和临时处理器
     const { req, res, reqId, isCancelledByClient, preliminaryCloseHandler } = queueItem;

     // --- 重要：立即移除临时监听器（如果存在且未被触发移除）---
     // 因为我们要么跳过处理，要么添加新的主监听器
     if (preliminaryCloseHandler) {
          // 使用 removeListener 以防万一它已被触发并自我移除
          res.removeListener('close', preliminaryCloseHandler);
     }
     // --- 结束移除临时监听器 ---

     // --- 新增：检查请求是否在处理前已被取消 ---
     if (isCancelledByClient) {
          console.log(`[${reqId}] Request was cancelled by client before processing began. Skipping.`);
          // 清理可能由其他地方（如主 close 事件处理器）设置的定时器，以防万一
          if (operationTimer) clearTimeout(operationTimer);
          // 标记处理结束（跳过），然后处理下一个
          isProcessing = false;
          processQueue(); // 尝试处理下一个请求
          return; // 退出当前 processQueue 调用
     }
     // --- 结束新增检查 ---

     console.log(`\n[${reqId}] ---开始处理队列中的请求 (剩余 ${requestQueue.length} 个)---`);

     let operationTimer; // 主操作定时器
     // *** 修改：将 isCancelledByClient 的状态传递给处理期间的 isCancelled 标志 ***
     let isCancelled = isCancelledByClient; 
     // 如果在开始处理时就已经被取消，添加一条日志
     if (isCancelled) {
          console.log(`[${reqId}] Warning: Request was cancelled very shortly before processing logic started.`);
          // 虽然上面的检查理论上会处理，但这里多一层保险
     }
     // *** 结束修改 ***
     let closeEventHandler = null; // 主 close 事件处理器引用

     try {
          // 1. 检查 Playwright 状态 (现在可以安全地继续，因为请求未被提前取消)
          // *** 新增：如果此时 isCancelled 已经是 true，则直接跳到 finally ***
          if (isCancelled) {
               console.log(`[${reqId}] Skipping Playwright interaction as request is already marked cancelled.`);
               throw new Error(`[${reqId}] Request pre-cancelled`); // 抛出错误以跳到 catch/finally
          }
          // *** 结束新增检查 ***
          
          if (!isPlaywrightReady && !isInitializing) {
               console.warn(`[${reqId}] Playwright 未就绪，尝试重新初始化...`);
               await initializePlaywright();
          }
          if (!isPlaywrightReady || !page || page.isClosed() || !browser?.isConnected()) {
               console.error(`[${reqId}] API 请求失败：Playwright 未就绪、页面关闭或连接断开。`);
               let detail = 'Unknown issue.';
               if (!browser?.isConnected()) detail = "Browser connection lost.";
               else if (!page || page.isClosed()) detail = "Target AI Studio page is not available or closed.";
               else if (!isPlaywrightReady) detail = "Playwright initialization failed or incomplete.";
               console.error(`[${reqId}] Playwright 连接不可用详情: ${detail}`);
               // 直接为当前请求返回错误，不需要抛出，因为要继续处理队列
               if (!res.headersSent) {
                    res.status(503).json({
                         error: { message: `[${reqId}] Playwright connection is not active. ${detail} Please ensure Chrome is running correctly, the AI Studio tab is open, and potentially restart the server.`, type: 'server_error' }
                    });
               }
               throw new Error("Playwright not ready for this request."); // Throw to skip further processing in try block
          }

          const { messages, stream, ...otherParams } = req.body;
          const isStreaming = stream === true;

          // --- 修改：基于消息数量启发式判断并执行清空操作 + 验证 ---
          const isLikelyNewChat = Array.isArray(messages) && (messages.length === 1 || (messages.length === 2 && messages.some(m => m.role === 'system')));

          if (isLikelyNewChat && CLEAR_CHAT_BUTTON_SELECTOR && CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR) {
              console.log(`[${reqId}] 检测到可能是新对话 (消息数: ${messages.length})，尝试清空聊天记录...`);
              try {
                  const clearButton = page.locator(CLEAR_CHAT_BUTTON_SELECTOR);
                  console.log(`[${reqId}]   - 查找并点击"Clear chat" (New chat) 按钮...`);
                  await clearButton.waitFor({ state: 'visible', timeout: 7000 });
                  await clearButton.click({ timeout: 5000 });
                  console.log(`[${reqId}]   - "Clear chat"按钮已点击。新版UI无确认步骤，开始验证清空效果...`);

                  const checkStartTime = Date.now();
                  let cleared = false;
                  while (Date.now() - checkStartTime < CLEAR_CHAT_VERIFY_TIMEOUT_MS) {
                      const modelTurns = page.locator(RESPONSE_CONTAINER_SELECTOR);
                      const count = await modelTurns.count();
                      if (count === 0) {
                          console.log(`[${reqId}]   ✅ 验证成功: 页面上未找到之前的 AI 回复元素 (耗时 ${Date.now() - checkStartTime}ms)。`);
                          cleared = true;
                          break;
                      }
                      await page.waitForTimeout(CLEAR_CHAT_VERIFY_INTERVAL_MS);
                  }

                  if (!cleared) {
                      console.warn(`[${reqId}]   ⚠️ 验证超时: 在 ${CLEAR_CHAT_VERIFY_TIMEOUT_MS}ms 内仍能检测到之前的 AI 回复元素。上下文可能未完全清空。`);
                      await saveErrorSnapshot(`clear_chat_verify_fail_${reqId}`);
                  }
              } catch (clearChatError) {
                  console.warn(`[${reqId}] ⚠️ 清空聊天记录或验证时出错: ${clearChatError.message.split('\n')[0]}. 将继续执行请求，但上下文可能未被清除。`);
                  if (clearChatError.message.includes('selector')) {
                       console.warn(`   (请仔细检查选择器是否仍然有效: CLEAR_CHAT_BUTTON_SELECTOR='${CLEAR_CHAT_BUTTON_SELECTOR}')`);
                  }
                  await saveErrorSnapshot(`clear_chat_fail_or_verify_${reqId}`);
              }
          } else if (isLikelyNewChat && (!CLEAR_CHAT_BUTTON_SELECTOR || !CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR)) {
              console.warn(`[${reqId}] 检测到可能是新对话，但未完整配置清空聊天相关的选择器常量，无法自动重置上下文。`);
          }
          // --- 结束：启发式新对话处理 ---

          console.log(`[${reqId}] 请求模式: ${isStreaming ? '流式 (SSE)' : '非流式 (JSON)'}`);

          // 2. 设置此请求的总操作超时
          operationTimer = setTimeout(async () => {
               await saveErrorSnapshot(`operation_timeout_${reqId}`);
               console.error(`[${reqId}] Operation timed out after ${RESPONSE_COMPLETION_TIMEOUT / 1000} seconds.`);
               if (!res.headersSent) {
                    res.status(504).json({ error: { message: `[${reqId}] Operation timed out`, type: 'timeout_error' } });
               } else if (isStreaming && !res.writableEnded) {
                    sendStreamError(res, "Operation timed out on server.", reqId);
               }
               // Note: Timeout error now managed within processQueue, allowing next item to proceed
          }, RESPONSE_COMPLETION_TIMEOUT);

          // 3. 验证请求 (使用更新后的函数)
          // Pass reqId to validation for better logging context
          const validationMessages = messages.map(m => ({ ...m, reqId })); // Add reqId temporarily
          const { userPrompt, systemPrompt: extractedSystemPrompt } = validateChatRequest(validationMessages);
          // Combine system prompts if provided in multiple ways
          const systemPrompt = extractedSystemPrompt || otherParams?.system_prompt;

          // --- Logging (Now userPrompt is guaranteed to be a string) ---
          const userPromptPreview = userPrompt.substring(0, 80);
          console.log(`[${reqId}]   处理后的 User Prompt (用于提交, start): \"${userPromptPreview}...\" (Total length: ${userPrompt.length})`);

          if (systemPrompt) {
               // systemPrompt from validateChatRequest is also guaranteed string or null
               const systemPromptPreview = systemPrompt.substring(0, 80);
               console.log(`[${reqId}]   处理后的 System Prompt (用于提交, start): \"${systemPromptPreview}...\"`);
          } else {
               console.log(`[${reqId}]   无 System Prompt。`);
          }
          if (Object.keys(otherParams).length > 0) {
                console.log(`[${reqId}]   记录到的额外参数: ${JSON.stringify(otherParams)}`);
          }
          // --- End Logging ---

          // 4. 准备 Prompt (使用处理后的 userPrompt 和 systemPrompt)
          let prompt;
          if (isStreaming) {
               prompt = prepareAIStudioPromptStream(userPrompt, systemPrompt); // Assumes prepare functions handle null systemPrompt
               console.log(`[${reqId}] 构建的流式 Prompt (Raw): \"${prompt.substring(0, 200)}...\"`);
          } else {
               prompt = prepareAIStudioPrompt(userPrompt, systemPrompt); // Assumes prepare functions handle null systemPrompt
               console.log(`[${reqId}] 构建的非流式 Prompt (JSON): \"${prompt.substring(0, 200)}...\"`);
          }

          // 5. 与页面交互并提交
          const locators = await interactAndSubmitPrompt(page, prompt, reqId);

          // --- 添加 'close' 事件监听器 ---
          closeEventHandler = async () => {
               console.log(`[${reqId}] 'close' event handler triggered.`); // <-- 新增日志
               if (isCancelled) {
                    console.log(`[${reqId}] 'close' event handler: Already cancelled, doing nothing.`); // <-- 新增日志
                    return; // 防止重复执行
               }
               isCancelled = true;
               console.log(`[${reqId}] Client disconnected ('close' event). Attempting to stop generation by clicking the run/stop button.`);
               clearTimeout(operationTimer); // 清除主超时定时器

               // 尝试点击运行/停止按钮 (因为它是同一个按钮)
               try {
                    // 确保 locators, submitButton, inputField 存在
                    if (!locators || !locators.submitButton || !locators.inputField) {
                         console.warn(`[${reqId}]   closeEventHandler: Cannot attempt to click stop button: locators (button or input) not available.`); // <-- 修改日志
                         return;
                    }
                    // 检查按钮是否仍然可用 (增加超时)
                    console.log(`[${reqId}]   closeEventHandler: Checking button state (timeout: 2000ms)...`); // <-- 修改日志
                    const isEnabled = await locators.submitButton.isEnabled({ timeout: 2000 }); // <-- 增加超时
                    console.log(`[${reqId}]   closeEventHandler: Button isEnabled result: ${isEnabled}`); // <-- 新增日志

                    if (isEnabled) {
                         // *** 新增：检查输入框是否为空 (增加超时) ***
                         console.log(`[${reqId}]   closeEventHandler: Button enabled, checking input value (timeout: 2000ms)...`); // <-- 修改日志
                         const inputValue = await locators.inputField.inputValue({ timeout: 2000 }); // <-- 增加超时
                         console.log(`[${reqId}]   closeEventHandler: Input value: "${inputValue}"`); // <-- 新增日志
                         if (inputValue === '') {
                              console.log(`[${reqId}]   closeEventHandler: Run/Stop button is enabled AND input is empty. Clicking it to stop generation...`); // <-- 修改日志
                              // 使用 click({ force: true }) 可能更可靠
                              await locators.submitButton.click({ timeout: 5000, force: true });
                              console.log(`[${reqId}]   closeEventHandler: Run/Stop button click attempted.`); // <-- 修改日志
                         } else {
                              console.log(`[${reqId}]   closeEventHandler: Run/Stop button is enabled BUT input is NOT empty. Assuming user typed new input, not clicking stop.`); // <-- 修改日志
                         }
                         // *** 结束新增检查 ***
                    } else {
                         console.log(`[${reqId}]   closeEventHandler: Run/Stop button is already disabled (generation likely finished or close event was late). No click needed.`); // <-- 修改日志
                    }
               } catch (clickError) {
                    // 捕获检查或点击过程中的错误
                    console.warn(`[${reqId}]   closeEventHandler: Error during stop button check/click: ${clickError.message.split('\n')[0]}`); // <-- 修改日志
                    // 添加更详细日志并尝试保存快照
                    console.error(`[${reqId}]   closeEventHandler: Detailed error during check/click:`, clickError); 
                    await saveErrorSnapshot(`close_handler_click_error_${reqId}`); 
               }
          };
          res.on('close', closeEventHandler);
          // --- 结束添加监听器 ---

          // 6. 定位响应元素
          const { responseElement } = await locateResponseElements(page, locators, reqId);

          // 7. 处理响应 (流式或非流式)
          console.log(`[${reqId}] 处理 AI 回复...`);
          if (isStreaming) {
               // --- 设置流式响应头 ---
               res.setHeader('Content-Type', 'text/event-stream');
               res.setHeader('Cache-Control', 'no-cache');
               res.setHeader('Connection', 'keep-alive');
               res.flushHeaders();

               // 调用流式处理函数
               // 传递检查函数 () => isCancelled
               await handleStreamingResponse(res, responseElement, page, locators, operationTimer, reqId, () => isCancelled);

          } else {
               // 调用非流式处理函数
               // 传递检查函数 () => isCancelled
               await handleNonStreamingResponse(res, page, locators, operationTimer, reqId, () => isCancelled);
          }

          // --- 修改：仅在未被取消时记录成功 --- 
          if (!isCancelled) {
               console.log(`[${reqId}] ✅ 请求处理成功完成。`);
               clearTimeout(operationTimer); // 只有真正成功完成才清除计时器
          } else {
               console.log(`[${reqId}] ℹ️ 请求处理因客户端断开连接而被中止。`);
               // operationTimer 应该已经在 closeEventHandler 中被清除了
          }
          // --- 结束修改 ---

     } catch (error) {
          // 确保在任何错误情况下都清除此请求的定时器 (如果 close 事件未触发)
          if (!isCancelled) {
               clearTimeout(operationTimer);
          }
          console.error(`[${reqId}] ❌ 处理队列中的请求时出错: ${error.message}\n${error.stack}`);

          // --- 恢复：添加条件判断是否需要保存快照 ---
          const shouldSaveSnapshot = !(
              error.message?.includes('Invalid request') || // 跳过请求验证错误
              error.message?.includes('Playwright not ready') // 跳过 Playwright 初始化/连接错误
              // 未来可以根据需要添加其他不需要快照的错误类型
          );

          if (shouldSaveSnapshot && !error.message?.includes('snapshot') && !error.stack?.includes('saveErrorSnapshot')) {
              // 避免在保存快照本身失败或已知Playwright问题时再次尝试保存
              await saveErrorSnapshot(`general_api_error_${reqId}`);
          } else if (!shouldSaveSnapshot) {
              console.log(`[${reqId}] (Info) Skipping error snapshot for this type of error: ${error.message.split('\n')[0]}`);
          }
          // --- 结束恢复 ---

          // 发送错误响应，如果尚未发送
          if (!res.headersSent) {
                let statusCode = 500;
                let errorType = 'server_error';
                if (error.message?.includes('timed out') || error.message?.includes('timeout')) {
                    statusCode = 504; // Gateway Timeout
                    errorType = 'timeout_error';
                } else if (error.message?.includes('AI Studio Error')) {
                    statusCode = 502; // Bad Gateway (error from upstream)
                    errorType = 'upstream_error';
                } else if (error.message?.includes('Invalid request')) {
                    statusCode = 400; // Bad Request
                    errorType = 'invalid_request_error';
                } else if (error.message?.includes('Playwright not ready')) { // Specific handling for PW not ready here
                    statusCode = 503;
                    errorType = 'server_error';
                }
               res.status(statusCode).json({ error: { message: `[${reqId}] ${error.message}`, type: errorType } });
          } else if (req.body.stream === true && !res.writableEnded) { // Check if it WAS a streaming request
                // 如果是流式响应且头部已发送，则发送流式错误
                sendStreamError(res, error.message, reqId);
          }
          else if (!res.writableEnded) {
                // 对于非流式但已发送部分内容的罕见情况，或流式错误发送后的清理
                res.end();
          }
     } finally {
          // --- 添加清理逻辑 ---
          if (closeEventHandler) {
               res.removeListener('close', closeEventHandler);
               // console.log(`[${reqId}] Removed 'close' event listener.`); // Optional debug log
          }
          // --- 结束清理逻辑 ---
          isProcessing = false; // 标记处理已结束
          console.log(`[${reqId}] ---结束处理队列中的请求---`);
          // 触发处理下一个请求（如果队列中有）
          processQueue();
     }
}

// --- API 端点 (v2.18: 使用队列) ---
app.post('/v1/chat/completions', async (req, res) => {
    const reqId = Math.random().toString(36).substring(2, 9); // 生成简短的请求 ID
    console.log(`\n[${reqId}] === 收到 /v1/chat/completions 请求 ===`);

    // 创建请求队列项，并添加取消标记和临时监听器引用
    const queueItem = {
         req,
         res,
         reqId,
         isCancelledByClient: false,
         preliminaryCloseHandler: null
    };

    // --- 添加临时的 'close' 事件监听器 ---
    queueItem.preliminaryCloseHandler = () => {
         if (!queueItem.isCancelledByClient) { // 避免重复标记
              console.log(`[${reqId}] Client disconnected before processing started.`);
              queueItem.isCancelledByClient = true;
              // 从 res 对象移除自身，防止后续冲突
              res.removeListener('close', queueItem.preliminaryCloseHandler);
         }
    };
    res.once('close', queueItem.preliminaryCloseHandler); // 使用 once 确保最多触发一次
    // --- 结束添加临时监听器 ---

    // 将请求加入队列
    requestQueue.push(queueItem); // <-- 推入包含标记的对象
    console.log(`[${reqId}] 请求已加入队列 (当前队列长度: ${requestQueue.length})`);

    // 尝试处理队列 (如果当前未在处理)
    if (!isProcessing) {
        console.log(`[Queue] 触发队列处理 (收到新请求 ${reqId} 时处于空闲状态)`);
        processQueue();
    } else {
         console.log(`[Queue] 当前正在处理其他请求，请求 ${reqId} 已排队等待。`);
    }
});


// --- Helper: 获取当前文本 (v2.14 - 获取原始文本) -> vNEXT: Try innerText
async function getRawTextContent(responseElement, previousText, reqId) {
    try {
         await responseElement.waitFor({ state: 'attached', timeout: 1500 });
         const preElement = responseElement.locator('pre').last();
         let rawText = null;
         try {
              await preElement.waitFor({ state: 'attached', timeout: 500 });
              // 尝试使用 innerText 获取渲染后的文本，可能更好地保留换行
              rawText = await preElement.innerText({ timeout: 1000 });
         } catch {
              // 如果 pre 元素获取失败，回退到 responseElement 的 innerText
              console.warn(`[${reqId}] (Warn) Failed to get innerText from <pre>, falling back to parent.`);
              rawText = await responseElement.innerText({ timeout: 2000 });
         }
         // 移除 trim()，直接返回获取到的文本
         return rawText !== null ? rawText : previousText;
    } catch (e) {
         console.warn(`[${reqId}] (Warn) getRawTextContent (innerText) failed: ${e.message.split('\n')[0]}. Returning previous.`);
         return previousText;
    }
}

// --- Helper: 发送流式块 ---
function sendStreamChunk(res, delta, reqId) {
    if (delta && !res.writableEnded) {
        const chunk = {
            id: `${CHAT_COMPLETION_ID_PREFIX}${Date.now()}-${Math.random().toString(36).substring(2, 15)}`,
            object: "chat.completion.chunk",
            created: Math.floor(Date.now() / 1000),
            model: MODEL_NAME,
            choices: [{ index: 0, delta: { content: delta }, finish_reason: null }]
        };
         try {
             res.write(`data: ${JSON.stringify(chunk)}\n\n`);
         } catch (writeError) {
              console.error(`[${reqId}] Error writing stream chunk:`, writeError.message);
              if (!res.writableEnded) res.end(); // End stream on write error
         }
    }
}

// --- Helper: 发送流式错误块 ---
function sendStreamError(res, errorMessage, reqId) {
     if (!res.writableEnded) {
         const errorPayload = { error: { message: `[${reqId}] Server error during streaming: ${errorMessage}`, type: 'server_error' } };
         try {
              // Avoid writing multiple DONE messages if error occurs after normal DONE
              if (!res.writableEnded) res.write(`data: ${JSON.stringify(errorPayload)}\n\n`);
              if (!res.writableEnded) res.write('data: [DONE]\n\n');
         } catch (e) {
             console.error(`[${reqId}] Error writing stream error chunk:`, e.message);
         } finally {
             if (!res.writableEnded) res.end(); // Ensure stream ends
         }
     }
}

// --- Helper: 保存错误快照 ---
async function saveErrorSnapshot(errorName = 'error') {
     // Extract reqId if present in the name
     const nameParts = errorName.split('_');
     const reqId = nameParts[nameParts.length - 1].length === 7 ? nameParts.pop() : null; // Simple check for likely reqId
     const baseErrorName = nameParts.join('_');
     const logPrefix = reqId ? `[${reqId}]` : '[No ReqId]';

     if (!browser?.isConnected() || !page || page.isClosed()) {
         console.log(`${logPrefix} 无法保存错误快照 (${baseErrorName})，浏览器或页面不可用。`);
         return;
     }
     console.log(`${logPrefix} 尝试保存错误快照 (${baseErrorName})...`);
     const timestamp = Date.now();
     const errorDir = path.join(__dirname, 'errors');
     try {
          if (!fs.existsSync(errorDir)) fs.mkdirSync(errorDir, { recursive: true });
          // Include reqId in filename if available
          const filenameSuffix = reqId ? `${reqId}_${timestamp}` : `${timestamp}`;
          const screenshotPath = path.join(errorDir, `${baseErrorName}_screenshot_${filenameSuffix}.png`);
          const htmlPath = path.join(errorDir, `${baseErrorName}_page_${filenameSuffix}.html`);

          try {
               await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 15000 });
               console.log(`${logPrefix}    错误快照已保存到: ${screenshotPath}`);
          } catch (screenshotError) {
               console.error(`${logPrefix}    保存屏幕截图失败 (${baseErrorName}): ${screenshotError.message}`);
          }
          try {
               const content = await page.content({timeout: 15000});
               fs.writeFileSync(htmlPath, content);
               console.log(`${logPrefix}    错误页面HTML已保存到: ${htmlPath}`);
          } catch (htmlError) {
                console.error(`${logPrefix}    保存页面HTML失败 (${baseErrorName}): ${htmlError.message}`);
          }
     } catch (dirError) {
          console.error(`${logPrefix}    创建错误目录或保存快照时出错: ${dirError.message}`);
     }
}

// v2.14: Helper to safely parse JSON, attempting to find the outermost object/array
function tryParseJson(text, reqId) {
    if (!text || typeof text !== 'string') return null;
    text = text.trim();

    let startIndex = -1;
    let endIndex = -1;

    const firstBrace = text.indexOf('{');
    const firstBracket = text.indexOf('[');

    if (firstBrace !== -1 && (firstBracket === -1 || firstBrace < firstBracket)) {
        startIndex = firstBrace;
        endIndex = text.lastIndexOf('}');
    } else if (firstBracket !== -1) {
        startIndex = firstBracket;
        endIndex = text.lastIndexOf(']');
    }

    if (startIndex === -1 || endIndex === -1 || endIndex < startIndex) {
        // console.warn(`[${reqId}] (Warn) Could not find valid start/end braces/brackets for JSON parsing.`);
        return null;
    }

    const jsonText = text.substring(startIndex, endIndex + 1);

    try {
        return JSON.parse(jsonText);
    } catch (e) {
         // console.warn(`[${reqId}] (Warn) JSON parse failed for extracted text: ${e.message}`);
        return null;
    }
}

// --- Helper: 检测并提取页面错误提示 ---
async function detectAndExtractPageError(page, reqId) {
    const errorToastLocator = page.locator(ERROR_TOAST_SELECTOR).last();
    try {
        const isVisible = await errorToastLocator.isVisible({ timeout: 1000 });
        if (isVisible) {
            console.log(`[${reqId}]    检测到错误 Toast 元素。`);
            const messageLocator = errorToastLocator.locator('span.content-text');
            const errorMessage = await messageLocator.textContent({ timeout: 500 });
            return errorMessage || "Detected error toast, but couldn't extract specific message.";
        } else {
             return null;
        }
    } catch (e) {
        // console.warn(`[${reqId}] (Warn) Checking for error toast failed or timed out: ${e.message.split('\n')[0]}`);
        return null;
    }
}

// --- Helper: 快速检查结束条件 ---
async function checkEndConditionQuickly(page, spinnerLocator, inputLocator, buttonLocator, timeoutMs = 250, reqId) {
    try {
        const results = await Promise.allSettled([
            expect(spinnerLocator).toBeHidden({ timeout: timeoutMs }),
            expect(inputLocator).toHaveValue('', { timeout: timeoutMs }),
            expect(buttonLocator).toBeDisabled({ timeout: timeoutMs })
        ]);
        const allMet = results.every(result => result.status === 'fulfilled');
        // console.log(`[${reqId}] (Quick Check) All met: ${allMet}`);
        return allMet;
    } catch (error) {
        // console.warn(`[${reqId}] (Quick Check) Error during checkEndConditionQuickly: ${error.message}`);
        return false;
    }
}

// --- 启动服务器 ---
let serverInstance = null;
(async () => {
    await initializePlaywright();

    serverInstance = app.listen(SERVER_PORT, () => {
        console.log("\n=============================================================");
        // v2.18: Updated version marker
        console.log("          🚀 AI Studio Proxy Server (v2.18 - Queue) 🚀");
        console.log("=============================================================");
        console.log(`🔗 监听地址: http://localhost:${SERVER_PORT}`);
        console.log(`   - Web UI (测试): http://localhost:${SERVER_PORT}/`);
        console.log(`   - API 端点:   http://localhost:${SERVER_PORT}/v1/chat/completions`);
        console.log(`   - 模型接口:   http://localhost:${SERVER_PORT}/v1/models`);
        console.log(`   - 健康检查:   http://localhost:${SERVER_PORT}/health`);
        console.log("-------------------------------------------------------------");
        if (isPlaywrightReady) {
            console.log('✅ Playwright 连接成功，服务已准备就绪！');
        } else {
            console.warn('⚠️ Playwright 未就绪。请检查下方日志并确保 Chrome/AI Studio 正常运行。');
            console.warn('   API 请求将失败，直到 Playwright 连接成功。');
        }
        console.log("-------------------------------------------------------------");
        console.log(`⏳ 等待 Chrome 实例 (调试端口: ${CHROME_DEBUGGING_PORT})...`);
        console.log("   请确保已运行 auto_connect_aistudio.js 脚本，");
        console.log("   并且 Google AI Studio 页面已在浏览器中打开。 ");
        console.log("=============================================================\n");
    });

    serverInstance.on('error', (error) => {
        if (error.code === 'EADDRINUSE') {
            console.error("\n=============================================================");
            console.error(`❌ 致命错误：端口 ${SERVER_PORT} 已被占用！`);
            console.error("   请关闭占用该端口的其他程序，或在 server.cjs 中修改 SERVER_PORT。 ");
            console.error("=============================================================\n");
        } else {
            console.error('❌ 服务器启动失败:', error);
        }
        process.exit(1);
    });

})();

// --- 优雅关闭处理 ---
let isShuttingDown = false;
async function shutdown(signal) {
    if (isShuttingDown) return;
    isShuttingDown = true;
    console.log(`\n收到 ${signal} 信号，正在关闭服务器...`);
    console.log(`当前队列中有 ${requestQueue.length} 个请求等待处理。将不再接受新请求。`);
    // Option: Wait for the current request to finish?
    // For now, we'll just close the server, potentially interrupting the current request.

    if (serverInstance) {
        serverInstance.close(async (err) => {
            if (err) console.error("关闭 HTTP 服务器时出错:", err);
            else console.log("HTTP 服务器已关闭。");

            console.log("Playwright connectOverCDP 将自动断开。");
            // No need to explicitly disconnect browser in connectOverCDP mode
            console.log('服务器优雅关闭完成。');
            process.exit(err ? 1 : 0);
        });

        // Force exit after timeout
        setTimeout(() => {
            console.error("优雅关闭超时，强制退出进程。");
            process.exit(1);
        }, 10000); // 10 seconds timeout
    } else {
        console.log("服务器实例未找到，直接退出。");
        process.exit(0);
    }
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM')); 