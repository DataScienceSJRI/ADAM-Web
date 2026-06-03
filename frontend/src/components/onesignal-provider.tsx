'use client';

import Script from 'next/script';
import { useEffect } from 'react';
import { createClient } from '@/lib/supabase/client';

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    OneSignalDeferred?: ((os: any) => void)[];
  }
}

const APP_ID = process.env.NEXT_PUBLIC_ONESIGNAL_APP_ID ?? '';
const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? '';

async function registerToken(playerId: string) {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) return;

  await fetch(`${BACKEND}/api/v1/notifications/register-token`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
    body: JSON.stringify({ device_token: playerId, platform: 'web' }),
  }).catch(() => {/* non-fatal */});
}

export function OneSignalProvider() {
  useEffect(() => {
    if (!APP_ID) return;

    window.OneSignalDeferred = window.OneSignalDeferred ?? [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    window.OneSignalDeferred.push(async (OneSignal: any) => {
      await OneSignal.init({
        appId: APP_ID,
        notifyButton: { enable: false },
        allowLocalhostAsSecureOrigin: process.env.NODE_ENV === 'development',
      });

      // Register immediately if already subscribed
      const isSubscribed = await OneSignal.User.PushSubscription.optedIn;
      if (isSubscribed) {
        const id = OneSignal.User.PushSubscription.id;
        if (id) await registerToken(id);
      }

      // Register when user subscribes
      OneSignal.User.PushSubscription.addEventListener('change', async (event: { current: { optedIn: boolean; id?: string } }) => {
        if (event.current.optedIn && event.current.id) {
          await registerToken(event.current.id);
        }
      });
    });
  }, []);

  if (!APP_ID) return null;

  return (
    <Script
      src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js"
      defer
      strategy="afterInteractive"
    />
  );
}

/**
 * Prompt the user for push permission.
 * Returns "granted" | "denied" | "no_sdk" | "error".
 */
export async function requestPushPermission(): Promise<"granted" | "denied" | "no_sdk" | "error"> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const OneSignal = (window as any).OneSignal;
  if (!OneSignal) return "no_sdk";
  try {
    await OneSignal.Notifications.requestPermission();
    const granted = await OneSignal.Notifications.permission;
    return granted ? "granted" : "denied";
  } catch {
    return "error";
  }
}
