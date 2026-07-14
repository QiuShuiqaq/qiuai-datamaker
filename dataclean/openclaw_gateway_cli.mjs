import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const WSL_DISTRO = "OpenClawGateway";
const WSL_USER = "openclaw";
const OPENCLAW_NODE = "/home/openclaw/.openclaw/tools/node-v22.22.2/bin/node";
const OPENCLAW_ENTRY =
  "/home/openclaw/.openclaw/tools/node-v22.22.2/lib/node_modules/openclaw/dist/entry.js";
const SESSIONS_ROOT = "/home/openclaw/.openclaw/agents/main/sessions";
const DEFAULT_MIN_TURNS = 5;
const DEFAULT_MAX_AUTO_TURNS = 3;
const DEFAULT_AUTO_FOLLOWUP_PROMPT =
  "请继续围绕当前主题补充一轮新的有效对话，提供新的信息，不要重复前文。";

function parseArgs(argv) {
  const positionals = [];
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      positionals.push(token);
      continue;
    }

    const [rawKey, inlineValue] = token.slice(2).split("=", 2);
    if (inlineValue !== undefined) {
      options[rawKey] = inlineValue;
      continue;
    }

    const next = argv[index + 1];
    if (next && !next.startsWith("--")) {
      options[rawKey] = next;
      index += 1;
    } else {
      options[rawKey] = true;
    }
  }
  return { positionals, options };
}

function toPositiveInt(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`Invalid positive integer value: ${value}`);
  }
  return parsed;
}

function toNonNegativeInt(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`Invalid non-negative integer value: ${value}`);
  }
  return parsed;
}

function toBoolean(value, fallback) {
  if (value === undefined) {
    return fallback;
  }
  if (typeof value === "boolean") {
    return value;
  }
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  throw new Error(`Invalid boolean value: ${value}`);
}

function slugify(value) {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function timestamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function cleanWslText(buffer) {
  return buffer
    .toString("utf8")
    .replace(/\u0000/g, "")
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("wsl: "))
    .join("\n")
    .trim();
}

function maybeParseJson(text) {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\"'\"'`)}'`;
}

function splitJsonl(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function previewText(value, maxChars = 80) {
  const normalized = String(value).replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, maxChars)}...`;
}

function summarizeError(error) {
  return error?.stack ?? String(error?.message ?? error);
}

function runWsl(args, { timeoutMs = 900000 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("wsl.exe", args, {
      windowsHide: true,
    });

    const stdoutChunks = [];
    const stderrChunks = [];

    child.stdout.on("data", (chunk) => stdoutChunks.push(chunk));
    child.stderr.on("data", (chunk) => stderrChunks.push(chunk));
    child.on("error", reject);

    const timeout = setTimeout(() => {
      child.kill();
      reject(new Error(`WSL command timed out after ${timeoutMs} ms: ${args.join(" ")}`));
    }, timeoutMs);

    child.on("close", (code) => {
      clearTimeout(timeout);
      const stdoutText = cleanWslText(Buffer.concat(stdoutChunks));
      const stderrText = cleanWslText(Buffer.concat(stderrChunks));
      if (code !== 0) {
        reject(
          new Error(
            `WSL command failed (${code}): ${args.join(" ")}${
              stderrText ? `\n${stderrText}` : ""
            }${stdoutText ? `\n${stdoutText}` : ""}`,
          ),
        );
        return;
      }

      resolve({
        stdoutText,
        stderrText,
        stdoutJson: maybeParseJson(stdoutText),
      });
    });
  });
}

function runWslBash(script, { timeoutMs = 900000 } = {}) {
  return runWsl(["-d", WSL_DISTRO, "-u", WSL_USER, "bash", "-lc", script], { timeoutMs });
}

function runOpenClaw(args, { timeoutMs = 900000 } = {}) {
  return runWsl(
    ["-d", WSL_DISTRO, "-u", WSL_USER, OPENCLAW_NODE, OPENCLAW_ENTRY, ...args],
    { timeoutMs },
  );
}

async function wslPathExists(wslPath) {
  const result = await runWslBash(
    `[ -e ${shellQuote(wslPath)} ] && printf '1' || printf '0'`,
    { timeoutMs: 30000 },
  );
  return result.stdoutText.trim() === "1";
}

async function readWslTextFile(wslPath, { optional = false } = {}) {
  try {
    const result = await runWslBash(`cat ${shellQuote(wslPath)}`, { timeoutMs: 30000 });
    return result.stdoutText;
  } catch (error) {
    if (optional) {
      return null;
    }
    throw error;
  }
}

async function readWslJsonFile(wslPath, { optional = false } = {}) {
  const text = await readWslTextFile(wslPath, { optional });
  if (text === null) {
    return null;
  }
  return JSON.parse(text);
}

async function readWslJsonlFile(wslPath, { optional = false } = {}) {
  const text = await readWslTextFile(wslPath, { optional });
  if (text === null) {
    return [];
  }
  return splitJsonl(text);
}

async function copyWslPathToWindows(sourceWslPath, targetWindowsPath, { recursive = false } = {}) {
  const targetPath = path.resolve(targetWindowsPath);
  if (!recursive) {
    const fileText = await readWslTextFile(sourceWslPath);
    ensureDir(path.dirname(targetPath));
    fs.writeFileSync(targetPath, fileText, "utf8");
    return;
  }

  ensureDir(targetPath);
  const result = await runWslBash(`find ${shellQuote(sourceWslPath)} -type f | sort`, {
    timeoutMs: 120000,
  });
  const files = result.stdoutText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const filePath of files) {
    const relativePath = path.posix.relative(sourceWslPath, filePath);
    const fileText = await readWslTextFile(filePath);
    const outputPath = path.join(targetPath, ...relativePath.split("/"));
    ensureDir(path.dirname(outputPath));
    fs.writeFileSync(outputPath, fileText, "utf8");
  }
}

function printUsage() {
  console.log(`Usage:
  node .\\dataclean\\openclaw_gateway_cli.mjs probe
  node .\\dataclean\\openclaw_gateway_cli.mjs list-sessions [--limit 20]
  node .\\dataclean\\openclaw_gateway_cli.mjs inspect-session --session-key <key> [--min-assistant-turns 5]
  node .\\dataclean\\openclaw_gateway_cli.mjs export-session --session-key <key>
  node .\\dataclean\\openclaw_gateway_cli.mjs run-tasks --tasks <tasks.jsonl> [--concurrency 2] [--timeout-ms 900000]

Run-tasks validation options:
  --min-user-turns 5
  --min-assistant-turns 5
  --min-thinking-turns 5
  --min-thinking-chars 0
  --min-assistant-text-chars 1
  --reject-empty-assistant true
  --reject-tool-results true
  --reject-tool-artifacts true
  --require-final-assistant true
  --max-auto-turns 3
  --auto-followup-prompt "继续围绕当前主题补充一轮新的有效对话，提供新的信息，不要重复前文。"
  --skip-export true

Task JSONL format:
  {"label":"task-001","turns":["第1轮提示词","第2轮提示词","第3轮提示词","第4轮提示词","第5轮提示词"]}

Optional per task fields:
  sessionKey, agentId, thinkingLevel, verboseLevel, model, timeoutSeconds,
  minUserTurns, minAssistantTurns, minThinkingTurns, minThinkingChars,
  minAssistantTextChars, rejectEmptyAssistant, rejectToolResults,
  rejectToolArtifacts, requireFinalAssistant, maxAutoTurns, autoFollowupPrompt
`);
}

function loadTasks(tasksPath) {
  const raw = fs.readFileSync(tasksPath, "utf8");
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const item = JSON.parse(line);
      const turns = Array.isArray(item.turns)
        ? item.turns
        : Array.isArray(item.messages)
          ? item.messages
          : typeof item.prompt === "string"
            ? [item.prompt]
            : [];
      if (turns.length === 0) {
        throw new Error(`Task line ${index + 1} is missing turns/messages/prompt`);
      }
      return {
        ...item,
        label: item.label ?? `task-${String(index + 1).padStart(3, "0")}`,
        turns,
      };
    });
}

function buildSessionKey(task, taskIndex) {
  if (typeof task.sessionKey === "string" && task.sessionKey.trim()) {
    return task.sessionKey.trim();
  }
  const labelPart = slugify(task.label) || `task-${taskIndex + 1}`;
  return `agent:${task.agentId ?? "main"}:batch-${labelPart}`;
}

function ensureUniqueSessionKeys(tasks) {
  const seen = new Map();
  for (let index = 0; index < tasks.length; index += 1) {
    const sessionKey = buildSessionKey(tasks[index], index);
    if (seen.has(sessionKey)) {
      throw new Error(`Duplicate sessionKey detected: ${sessionKey}`);
    }
    seen.set(sessionKey, index);
  }
}

function extractTextSegments(content) {
  if (typeof content === "string") {
    return [content];
  }
  if (!Array.isArray(content)) {
    return [];
  }
  const parts = [];
  for (const item of content) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (item.type === "text" && typeof item.text === "string") {
      parts.push(item.text);
    }
  }
  return parts;
}

function extractThinkingSegments(content) {
  if (!Array.isArray(content)) {
    return [];
  }
  const parts = [];
  for (const item of content) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (item.type === "thinking" && typeof item.thinking === "string") {
      parts.push(item.thinking);
    }
  }
  return parts;
}

function extractToolResultSegments(content) {
  if (!Array.isArray(content)) {
    return [];
  }
  const parts = [];
  for (const item of content) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (item.type === "tool_result" && typeof item.content === "string") {
      parts.push(item.content);
    }
  }
  return parts;
}

function hasNonEmptySegment(items) {
  return items.some((item) => typeof item === "string" && item.trim().length > 0);
}

function messageHasToolResult(message) {
  return extractToolResultSegments(message.content).length > 0;
}

function messageTextForScan(message) {
  return [...extractTextSegments(message.content), ...extractToolResultSegments(message.content)].join("\n");
}

function assistantMessageHasText(message) {
  return hasNonEmptySegment(extractTextSegments(message.content));
}

function assistantMessageIsEmpty(message) {
  if (typeof message.content === "string") {
    return message.content.trim().length === 0;
  }
  if (!Array.isArray(message.content)) {
    return true;
  }
  if (message.content.length === 0) {
    return true;
  }
  return !hasNonEmptySegment(extractTextSegments(message.content)) &&
    !hasNonEmptySegment(extractThinkingSegments(message.content)) &&
    !hasNonEmptySegment(extractToolResultSegments(message.content));
}

function containsSerializedToolCall(text) {
  return /"type"\s*:\s*"toolCall"/i.test(text);
}

function containsValidationFailure(text) {
  return /validation failed for tool/i.test(text);
}

function containsToolArtifactText(text) {
  return containsSerializedToolCall(text) || containsValidationFailure(text);
}

function messageStartsWithSlash(message) {
  const text = extractTextSegments(message.content).join("\n").trim();
  return text.startsWith("/");
}

function isGatewayInjectedAssistant(message) {
  return message.provider === "openclaw" || message.model === "gateway-injected";
}

function buildValidationPolicy(task, options) {
  const minUserTurns = toPositiveInt(task.minUserTurns ?? options["min-user-turns"], DEFAULT_MIN_TURNS);
  const minAssistantTurns = toPositiveInt(
    task.minAssistantTurns ?? options["min-assistant-turns"],
    DEFAULT_MIN_TURNS,
  );
  const minThinkingTurns = toPositiveInt(
    task.minThinkingTurns ?? options["min-thinking-turns"],
    minAssistantTurns,
  );
  const minThinkingChars = toNonNegativeInt(
    task.minThinkingChars ?? options["min-thinking-chars"],
    0,
  );
  const minAssistantTextChars = toNonNegativeInt(
    task.minAssistantTextChars ?? options["min-assistant-text-chars"],
    1,
  );
  const rejectEmptyAssistant = toBoolean(
    task.rejectEmptyAssistant ?? options["reject-empty-assistant"],
    true,
  );
  const rejectToolResults = toBoolean(
    task.rejectToolResults ?? options["reject-tool-results"],
    true,
  );
  const rejectToolArtifacts = toBoolean(
    task.rejectToolArtifacts ??
      task.rejectToolErrors ??
      options["reject-tool-artifacts"] ??
      options["reject-tool-errors"],
    true,
  );
  const requireFinalAssistant = toBoolean(
    task.requireFinalAssistant ?? options["require-final-assistant"],
    true,
  );
  const maxAutoTurns = toNonNegativeInt(task.maxAutoTurns ?? options["max-auto-turns"], DEFAULT_MAX_AUTO_TURNS);
  const autoFollowupPrompt = String(
    task.autoFollowupPrompt ?? options["auto-followup-prompt"] ?? DEFAULT_AUTO_FOLLOWUP_PROMPT,
  ).trim();

  return {
    minUserTurns,
    minAssistantTurns,
    minThinkingTurns,
    minThinkingChars,
    minAssistantTextChars,
    rejectEmptyAssistant,
    rejectToolResults,
    rejectToolArtifacts,
    requireFinalAssistant,
    maxAutoTurns,
    autoFollowupPrompt,
  };
}

async function readSessionsStore() {
  return readWslJsonFile(`${SESSIONS_ROOT}/sessions.json`);
}

async function resolveTrajectoryRuntimeFile(sessionId) {
  const pointerPath = `${SESSIONS_ROOT}/${sessionId}.trajectory-path.json`;
  const pointer = await readWslJsonFile(pointerPath, { optional: true });
  if (pointer?.runtimeFile) {
    return pointer.runtimeFile;
  }

  const directPath = `${SESSIONS_ROOT}/${sessionId}.trajectory.jsonl`;
  if (await wslPathExists(directPath)) {
    return directPath;
  }
  return null;
}

function computeSessionMetrics(sessionEntries, trajectoryEntries) {
  const transcriptMessages = sessionEntries
    .filter((entry) => entry.type === "message" && entry.message)
    .map((entry) => entry.message);

  const userMessages = transcriptMessages.filter(
    (message) => message.role === "user" && !messageStartsWithSlash(message) && !messageHasToolResult(message),
  );
  const assistantMessages = transcriptMessages.filter(
    (message) => message.role === "assistant" && !isGatewayInjectedAssistant(message),
  );

  const thinkingPerAssistant = assistantMessages.map((message) => extractThinkingSegments(message.content));
  const thinkingTurns = thinkingPerAssistant.filter((items) => items.length > 0).length;
  const totalThinkingChars = thinkingPerAssistant
    .flat()
    .reduce((sum, text) => sum + text.length, 0);
  const totalAssistantTextChars = assistantMessages
    .flatMap((message) => extractTextSegments(message.content))
    .reduce((sum, text) => sum + text.length, 0);
  const assistantTextTurns = assistantMessages.filter((message) => assistantMessageHasText(message)).length;
  const emptyAssistantTurns = assistantMessages.filter((message) => assistantMessageIsEmpty(message)).length;
  const toolResultUserTurns = transcriptMessages.filter(
    (message) => message.role === "user" && messageHasToolResult(message),
  ).length;
  const assistantToolArtifactTurns = assistantMessages.filter((message) =>
    containsToolArtifactText(messageTextForScan(message))
  ).length;
  const userToolArtifactTurns = transcriptMessages.filter((message) =>
    message.role === "user" && containsToolArtifactText(messageTextForScan(message))
  ).length;
  const totalTokens = assistantMessages.reduce((sum, message) => {
    const tokens = message.usage?.totalTokens;
    return sum + (typeof tokens === "number" ? tokens : 0);
  }, 0);
  const lastRelevantMessage =
    [...transcriptMessages]
      .reverse()
      .find(
        (message) =>
          !messageStartsWithSlash(message) &&
          !(message.role === "assistant" && isGatewayInjectedAssistant(message)),
      ) ?? null;
  const endsWithAssistant = lastRelevantMessage?.role === "assistant";
  const finalAssistantHasText = endsWithAssistant ? assistantMessageHasText(lastRelevantMessage) : false;
  const lastThinkingLevel =
    [...sessionEntries]
      .reverse()
      .find((entry) => entry.type === "thinking_level_change" && typeof entry.thinkingLevel === "string")
      ?.thinkingLevel ?? null;
  const completedRuns = trajectoryEntries.filter((entry) => entry.type === "model.completed").length;

  return {
    userTurns: userMessages.length,
    assistantTurns: assistantMessages.length,
    assistantThinkingTurns: thinkingTurns,
    totalThinkingChars,
    totalAssistantTextChars,
    assistantTextTurns,
    emptyAssistantTurns,
    toolResultUserTurns,
    assistantToolArtifactTurns,
    userToolArtifactTurns,
    endsWithAssistant,
    finalAssistantHasText,
    totalTokens,
    lastThinkingLevel,
    completedRuns,
  };
}

function evaluateMetrics(metrics, policy) {
  const reasons = [];
  if (metrics.userTurns < policy.minUserTurns) {
    reasons.push(`userTurns ${metrics.userTurns} < ${policy.minUserTurns}`);
  }
  if (metrics.assistantTurns < policy.minAssistantTurns) {
    reasons.push(`assistantTurns ${metrics.assistantTurns} < ${policy.minAssistantTurns}`);
  }
  if (metrics.assistantThinkingTurns < policy.minThinkingTurns) {
    reasons.push(
      `assistantThinkingTurns ${metrics.assistantThinkingTurns} < ${policy.minThinkingTurns}`,
    );
  }
  if (metrics.totalThinkingChars < policy.minThinkingChars) {
    reasons.push(`thinkingChars ${metrics.totalThinkingChars} < ${policy.minThinkingChars}`);
  }
  if (metrics.totalAssistantTextChars < policy.minAssistantTextChars) {
    reasons.push(`assistantTextChars ${metrics.totalAssistantTextChars} < ${policy.minAssistantTextChars}`);
  }
  if (policy.rejectEmptyAssistant && metrics.emptyAssistantTurns > 0) {
    reasons.push(`emptyAssistantTurns ${metrics.emptyAssistantTurns} > 0`);
  }
  if (policy.rejectToolResults && metrics.toolResultUserTurns > 0) {
    reasons.push(`toolResultUserTurns ${metrics.toolResultUserTurns} > 0`);
  }
  if (policy.rejectToolArtifacts && metrics.assistantToolArtifactTurns > 0) {
    reasons.push(`assistantToolArtifactTurns ${metrics.assistantToolArtifactTurns} > 0`);
  }
  if (policy.rejectToolArtifacts && metrics.userToolArtifactTurns > 0) {
    reasons.push(`userToolArtifactTurns ${metrics.userToolArtifactTurns} > 0`);
  }
  if (policy.requireFinalAssistant && !metrics.endsWithAssistant) {
    reasons.push("final message is not assistant");
  }
  if (policy.requireFinalAssistant && metrics.endsWithAssistant && !metrics.finalAssistantHasText) {
    reasons.push("final assistant message has no text");
  }

  return {
    passed: reasons.length === 0,
    reasons,
  };
}

async function inspectSessionByKey(sessionKey, policy = null) {
  const sessionsStore = await readSessionsStore();
  const sessionRecord = sessionsStore?.[sessionKey];
  if (!sessionRecord?.sessionFile || !sessionRecord?.sessionId) {
    throw new Error(`Session not found in sessions.json: ${sessionKey}`);
  }

  const sessionEntries = await readWslJsonlFile(sessionRecord.sessionFile);
  const trajectoryFile = await resolveTrajectoryRuntimeFile(sessionRecord.sessionId);
  const trajectoryEntries = trajectoryFile ? await readWslJsonlFile(trajectoryFile, { optional: true }) : [];
  const metrics = computeSessionMetrics(sessionEntries, trajectoryEntries);
  const evaluation = policy ? evaluateMetrics(metrics, policy) : null;

  return {
    sessionKey,
    sessionRecord,
    sessionEntries,
    trajectoryFile,
    trajectoryEntries,
    metrics,
    evaluation,
  };
}

function buildAgentArgs(task, sessionKey, message) {
  const args = ["agent", "--json", "--session-key", sessionKey, "--message", message];
  const agentId = task.agentId ?? "main";
  args.push("--agent", agentId);

  if (task.thinkingLevel) {
    args.push("--thinking", String(task.thinkingLevel));
  }
  if (task.verboseLevel) {
    args.push("--verbose", String(task.verboseLevel));
  }
  if (task.model) {
    args.push("--model", String(task.model));
  }
  if (task.timeoutSeconds) {
    args.push("--timeout", String(task.timeoutSeconds));
  }

  return args;
}

async function sendTaskTurn(task, sessionKey, message, timeoutMs) {
  const startedAt = Date.now();
  const result = await runOpenClaw(buildAgentArgs(task, sessionKey, message), { timeoutMs });
  return {
    messagePreview: previewText(message),
    elapsedMs: Date.now() - startedAt,
    stdoutJson: result.stdoutJson,
    stdoutText: result.stdoutText,
  };
}

function summarizeTurnResult(turnResult) {
  return {
    messagePreview: turnResult.messagePreview,
    elapsedMs: turnResult.elapsedMs,
  };
}

async function exportAcceptedArtifacts(runRoot, taskLabel, sessionInfo) {
  const slug = slugify(taskLabel) || slugify(sessionInfo.sessionKey) || "task";
  const targetDir = path.join(runRoot, "accepted", slug);
  ensureDir(targetDir);

  const sessionJsonlPath = path.join(targetDir, "session.jsonl");
  await copyWslPathToWindows(sessionInfo.sessionRecord.sessionFile, sessionJsonlPath);

  const exportedFiles = [sessionJsonlPath];

  if (sessionInfo.trajectoryFile) {
    const trajectoryJsonlPath = path.join(targetDir, "trajectory.jsonl");
    await copyWslPathToWindows(sessionInfo.trajectoryFile, trajectoryJsonlPath);
    exportedFiles.push(trajectoryJsonlPath);
  }

  const exportName = `dataclean-${timestamp()}-${slug}`;
  const exportResult = await runOpenClaw(
    ["sessions", "export-trajectory", "--json", "--session-key", sessionInfo.sessionKey, "--output", exportName],
    { timeoutMs: 120000 },
  );
  const outputDir = exportResult.stdoutJson?.outputDir;
  if (typeof outputDir === "string" && outputDir) {
    const exportTargetDir = path.join(targetDir, "trajectory-export");
    await copyWslPathToWindows(outputDir, exportTargetDir, { recursive: true });
    exportedFiles.push(exportTargetDir);
  }

  const metadataPath = path.join(targetDir, "session-metadata.json");
  fs.writeFileSync(
    metadataPath,
    JSON.stringify(
      {
        sessionKey: sessionInfo.sessionKey,
        sessionRecord: sessionInfo.sessionRecord,
        metrics: sessionInfo.metrics,
        evaluation: sessionInfo.evaluation,
      },
      null,
      2,
    ),
    "utf8",
  );
  exportedFiles.push(metadataPath);

  return {
    targetDir,
    exportedFiles,
  };
}

async function commandProbe() {
  const sessions = await runOpenClaw(["sessions", "--json", "--limit", "3"], { timeoutMs: 30000 });
  console.log("WSL Distro:", WSL_DISTRO);
  console.log("CLI Entry:", OPENCLAW_ENTRY);
  console.log("Session Count:", sessions.stdoutJson?.count ?? 0);
  console.log(JSON.stringify(sessions.stdoutJson ?? sessions.stdoutText, null, 2));
}

async function commandListSessions(options) {
  const limit = options.limit ?? "20";
  const result = await runOpenClaw(["sessions", "--json", "--limit", String(limit)], {
    timeoutMs: 30000,
  });
  const sessions = result.stdoutJson?.sessions ?? [];
  for (const session of sessions) {
    console.log(
      [
        session.key ?? "",
        session.agentId ?? "",
        session.model ?? "",
        session.updatedAt ?? "",
      ].join("\t"),
    );
  }
}

async function commandInspectSession(options) {
  const sessionKey = String(options["session-key"] ?? "").trim();
  if (!sessionKey) {
    throw new Error("--session-key is required");
  }
  const policy = buildValidationPolicy({}, options);
  const sessionInfo = await inspectSessionByKey(sessionKey, policy);
  console.log(
    JSON.stringify(
      {
        sessionKey,
        sessionRecord: sessionInfo.sessionRecord,
        metrics: sessionInfo.metrics,
        evaluation: sessionInfo.evaluation,
        trajectoryFile: sessionInfo.trajectoryFile,
      },
      null,
      2,
    ),
  );
}

async function commandExportSession(options) {
  const sessionKey = String(options["session-key"] ?? "").trim();
  if (!sessionKey) {
    throw new Error("--session-key is required");
  }

  const runRoot = path.resolve(path.join(__dirname, "runs", `manual-export-${timestamp()}`));
  ensureDir(runRoot);
  const policy = buildValidationPolicy({}, options);
  const sessionInfo = await inspectSessionByKey(sessionKey, policy);
  const exportInfo = await exportAcceptedArtifacts(runRoot, sessionKey, sessionInfo);
  console.log(
    JSON.stringify(
      {
        runRoot,
        sessionKey,
        metrics: sessionInfo.metrics,
        evaluation: sessionInfo.evaluation,
        exportInfo,
      },
      null,
      2,
    ),
  );
}

async function runTask(task, taskIndex, timeoutMs, options, runRoot) {
  const sessionKey = buildSessionKey(task, taskIndex);
  const policy = buildValidationPolicy(task, options);
  const sendHistory = [];

  for (let index = 0; index < task.turns.length; index += 1) {
    const message = String(task.turns[index]).trim();
    if (!message) {
      continue;
    }

    const turnResult = await sendTaskTurn(task, sessionKey, message, timeoutMs);
    sendHistory.push({
      stage: "initial",
      index: index + 1,
      ...summarizeTurnResult(turnResult),
    });
  }

  let sessionInfo = await inspectSessionByKey(sessionKey, policy);
  let autoTurnsUsed = 0;
  while (!sessionInfo.evaluation.passed && autoTurnsUsed < policy.maxAutoTurns) {
    autoTurnsUsed += 1;
    const turnResult = await sendTaskTurn(task, sessionKey, policy.autoFollowupPrompt, timeoutMs);
    sendHistory.push({
      stage: "auto",
      index: autoTurnsUsed,
      ...summarizeTurnResult(turnResult),
    });
    sessionInfo = await inspectSessionByKey(sessionKey, policy);
  }

  let exportInfo = null;
  if (sessionInfo.evaluation.passed && !toBoolean(options["skip-export"], false)) {
    exportInfo = await exportAcceptedArtifacts(runRoot, task.label, sessionInfo);
  }

  return {
    label: task.label,
    sessionKey,
    sessionId: sessionInfo.sessionRecord.sessionId,
    sessionFile: sessionInfo.sessionRecord.sessionFile,
    initialTurnCount: task.turns.length,
    totalSentTurnCount: sendHistory.length,
    autoTurnsUsed,
    policy,
    metrics: sessionInfo.metrics,
    acceptance: sessionInfo.evaluation,
    sendHistory,
    exportInfo,
  };
}

async function commandRunTasks(options) {
  if (!options.tasks) {
    throw new Error("--tasks is required");
  }

  const tasksPath = path.resolve(options.tasks);
  const tasks = loadTasks(tasksPath);
  ensureUniqueSessionKeys(tasks);

  const concurrency = toPositiveInt(options.concurrency, 1);
  const timeoutMs = toPositiveInt(options["timeout-ms"], 900000);
  const runRoot = path.resolve(path.join(__dirname, "runs", `gateway-batch-${timestamp()}`));
  ensureDir(runRoot);

  const resultPath = path.join(runRoot, "results.jsonl");
  const stream = fs.createWriteStream(resultPath, { flags: "a", encoding: "utf8" });
  let cursor = 0;
  const acceptedResults = [];
  const rejectedResults = [];

  async function worker(workerIndex) {
    while (cursor < tasks.length) {
      const taskIndex = cursor;
      cursor += 1;
      const task = tasks[taskIndex];
      console.log(`[worker-${workerIndex}] start ${task.label}`);
      try {
        const result = await runTask(task, taskIndex, timeoutMs, options, runRoot);
        stream.write(`${JSON.stringify({ ok: true, ...result })}\n`);
        if (result.acceptance.passed) {
          acceptedResults.push(result);
          console.log(`[worker-${workerIndex}] pass ${task.label} -> ${result.sessionKey}`);
        } else {
          rejectedResults.push(result);
          console.log(
            `[worker-${workerIndex}] reject ${task.label}: ${result.acceptance.reasons.join("; ")}`,
          );
        }
      } catch (error) {
        const failed = {
          ok: false,
          label: task.label,
          sessionKey: buildSessionKey(task, taskIndex),
          error: summarizeError(error),
        };
        rejectedResults.push(failed);
        stream.write(`${JSON.stringify(failed)}\n`);
        console.log(`[worker-${workerIndex}] fail ${task.label}: ${String(error?.message ?? error)}`);
      }
    }
  }

  try {
    await Promise.all(Array.from({ length: concurrency }, (_, index) => worker(index + 1)));
  } finally {
    stream.end();
  }

  const acceptedPath = path.join(runRoot, "accepted.json");
  const rejectedPath = path.join(runRoot, "rejected.json");
  const summaryPath = path.join(runRoot, "summary.json");

  fs.writeFileSync(acceptedPath, JSON.stringify(acceptedResults, null, 2), "utf8");
  fs.writeFileSync(rejectedPath, JSON.stringify(rejectedResults, null, 2), "utf8");
  fs.writeFileSync(
    summaryPath,
    JSON.stringify(
      {
        tasksPath,
        totalTasks: tasks.length,
        acceptedTasks: acceptedResults.length,
        rejectedTasks: rejectedResults.length,
        concurrency,
        timeoutMs,
        defaultValidation: buildValidationPolicy({}, options),
        acceptedLabels: acceptedResults.map((item) => item.label),
        rejectedLabels: rejectedResults.map((item) => item.label),
      },
      null,
      2,
    ),
    "utf8",
  );

  console.log("Run Root:", runRoot);
  console.log("Result File:", resultPath);
  console.log("Accepted File:", acceptedPath);
  console.log("Rejected File:", rejectedPath);
  console.log("Summary File:", summaryPath);
}

async function main() {
  const { positionals, options } = parseArgs(process.argv.slice(2));
  const command = positionals[0];

  if (!command || command === "help" || command === "--help") {
    printUsage();
    return;
  }

  if (command === "probe") {
    await commandProbe();
    return;
  }

  if (command === "list-sessions") {
    await commandListSessions(options);
    return;
  }

  if (command === "inspect-session") {
    await commandInspectSession(options);
    return;
  }

  if (command === "export-session") {
    await commandExportSession(options);
    return;
  }

  if (command === "run-tasks") {
    await commandRunTasks(options);
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  console.error(summarizeError(error));
  process.exitCode = 1;
});
