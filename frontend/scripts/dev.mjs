import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectDir = path.resolve(frontendDir, "..");
const children = [
  spawn("python3", [path.join(projectDir, "serverless", "dev_server.py")], {
    cwd: projectDir,
    env: process.env,
    stdio: "inherit",
  }),
  spawn("vite", [], {
    cwd: frontendDir,
    env: process.env,
    stdio: "inherit",
  }),
];

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  children.forEach((child) => child.kill("SIGTERM"));
  setTimeout(() => process.exit(code), 50);
}

children.forEach((child) => child.on("exit", (code, signal) => {
  if (!stopping && (code !== 0 || signal)) stop(code ?? 1);
}));
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
