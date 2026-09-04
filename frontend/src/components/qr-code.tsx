"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";

export function QrCode({ value, size = 200 }: { value: string; size?: number }) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(value, { width: size, margin: 1 }).then((url) => {
      if (!cancelled) setDataUrl(url);
    });
    return () => {
      cancelled = true;
    };
  }, [value, size]);

  if (!dataUrl) {
    return <div className="rounded-lg bg-muted animate-pulse" style={{ width: size, height: size }} />;
  }

  // eslint-disable-next-line @next/next/no-img-element -- data: URL, no next/image benefit
  return <img src={dataUrl} alt="QR code" width={size} height={size} className="rounded-lg border" />;
}
