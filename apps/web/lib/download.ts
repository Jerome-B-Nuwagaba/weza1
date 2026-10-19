import { api } from "@/lib/api";

/** Download a file from an authenticated API route. Throws the API error (e.g. 403) so callers can show it. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const r: Response = await api(path, { raw: true });
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
