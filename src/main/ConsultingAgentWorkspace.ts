import { app } from "electron";
import { mkdirSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import * as dotenv from "dotenv";

dotenv.config({ path: join(__dirname, "../../.env") });

export const BLUEBARRY_AGENT_DESKTOP_FOLDER_ENV_KEY =
  "BLUEBARRY_AGENT_DESKTOP_FOLDER";
export const BLUEBERRY_AGENT_DESKTOP_FOLDER_ENV_KEY =
  "BLUEBERRY_AGENT_DESKTOP_FOLDER";
export const DEFAULT_BLUEBARRY_AGENT_DESKTOP_FOLDER = "BLUEBARRY";
const BLUEBERRY_DESKTOP_FOLDER_ALIAS = "BLUEBERRY";

export const getConsultingAgentDesktopFolderName = (): string => {
  const configuredFolderName =
    process.env[BLUEBARRY_AGENT_DESKTOP_FOLDER_ENV_KEY]?.trim() ||
    process.env[BLUEBERRY_AGENT_DESKTOP_FOLDER_ENV_KEY]?.trim();

  return configuredFolderName || DEFAULT_BLUEBARRY_AGENT_DESKTOP_FOLDER;
};

export const getConsultingAgentDesktopRootPath = (): string => {
  const desktopWorkspacePath = resolve(
    app.getPath("desktop"),
    getConsultingAgentDesktopFolderName()
  );

  mkdirSync(desktopWorkspacePath, { recursive: true });

  return desktopWorkspacePath;
};

const isPathInsideRoot = (rootPath: string, targetPath: string): boolean => {
  const relativePath = relative(rootPath, targetPath);
  return (
    relativePath === "" ||
    (!relativePath.startsWith("..") && !isAbsolute(relativePath))
  );
};

export const coerceConsultingAgentPathToDesktopRoot = (
  targetPath: string,
  desktopRootPath: string = getConsultingAgentDesktopRootPath()
): string => {
  const resolvedDesktopRootPath = resolve(desktopRootPath);
  const resolvedTargetPath = resolve(targetPath);

  if (isPathInsideRoot(resolvedDesktopRootPath, resolvedTargetPath)) {
    return resolvedTargetPath;
  }

  if (
    basename(resolvedDesktopRootPath).toLowerCase() !==
    DEFAULT_BLUEBARRY_AGENT_DESKTOP_FOLDER.toLowerCase()
  ) {
    return resolvedTargetPath;
  }

  const aliasRootPath = resolve(
    dirname(resolvedDesktopRootPath),
    BLUEBERRY_DESKTOP_FOLDER_ALIAS
  );

  if (!isPathInsideRoot(aliasRootPath, resolvedTargetPath)) {
    return resolvedTargetPath;
  }

  const aliasRelativePath = relative(aliasRootPath, resolvedTargetPath);
  return resolve(resolvedDesktopRootPath, aliasRelativePath);
};
