import { UPLOAD_MAX_BYTES } from "@/lib/report-form";

const EXTENSIONS = [".zip", ".tar.gz", ".tgz", ".tar"];

const trimmed = (n: number) => n.toFixed(1).replace(/\.0$/, "");

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${trimmed(bytes / 1024)} KB`;
  return `${trimmed(bytes / (1024 * 1024))} MB`;
}

/**
 * Cheap checks done in the browser so a bad pick fails at once instead of after an upload. The
 * server validates the archive for real; this only saves a round trip.
 */
export function checkArchive(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (!EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `"${file.name}" is not a supported archive. Use .zip, .tar, .tar.gz or .tgz.`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > UPLOAD_MAX_BYTES) {
    return `"${file.name}" is ${formatBytes(file.size)}, over the ${formatBytes(UPLOAD_MAX_BYTES)} limit.`;
  }
  return null;
}
