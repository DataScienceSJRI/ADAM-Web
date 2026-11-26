import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const IST_TIME_ZONE = "Asia/Kolkata";

export function formatIST(iso: string | Date, options: Intl.DateTimeFormatOptions = {}): string {
  const date = typeof iso === "string" ? new Date(iso) : iso;
  return date.toLocaleString("en-IN", { ...options, timeZone: IST_TIME_ZONE });
}
export function resizedImageUrl(url: string | null | undefined, width: number, quality = 70): string | null {
  if (!url) return null;
  const marker = "/storage/v1/object/public/";
  const idx = url.indexOf(marker);
  if (idx === -1) return url;
  const rendered = `${url.slice(0, idx)}/storage/v1/render/image/public/${url.slice(idx + marker.length)}`;
  const sep = rendered.includes("?") ? "&" : "?";
  return `${rendered}${sep}width=${width}&quality=${quality}&resize=contain`;
}
