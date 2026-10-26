"use client";

import { useEffect, useRef, useState } from "react";

export type Person = { name: string; initials: string; hue: number; editing: boolean; you: boolean };
export type LiveEvent = { type: "saved"; revision: number; by: string } | { type: "deleted"; by: string };

// The server closes with these when it will never let us in: don't keep retrying.
const REFUSED = [4403, 4404];

/** The workflow's live channel: who has it open, and what they just did.
 *  Same origin as the page (Next.js proxies the WebSocket to FastAPI), so the
 *  session cookie goes along. Reconnects with a growing pause if the line drops. */
export function useLive(workflowId: string, editing: boolean, onEvent: (event: LiveEvent) => void) {
  const [people, setPeople] = useState<Person[]>([]);
  const [online, setOnline] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const handler = useRef(onEvent);
  const editingNow = useRef(editing);

  useEffect(() => {
    handler.current = onEvent;
  });

  useEffect(() => {
    let stopped = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;

    function open() {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${scheme}://${window.location.host}/api/workflows/${workflowId}/live`);
      socket.current = ws;
      ws.onopen = () => {
        attempt = 0;
        setOnline(true);
        if (editingNow.current) ws.send(JSON.stringify({ type: "editing", editing: true }));
      };
      ws.onmessage = (message) => {
        const data = JSON.parse(message.data);
        if (data.type === "presence") setPeople(data.people);
        else handler.current(data as LiveEvent);
      };
      ws.onclose = (event) => {
        setOnline(false);
        setPeople([]);
        if (stopped || REFUSED.includes(event.code)) return;
        retry = setTimeout(open, Math.min(30_000, 1000 * 2 ** attempt++));
      };
    }

    open();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [workflowId]);

  // Tell the others when we start or stop having unsaved changes.
  useEffect(() => {
    editingNow.current = editing;
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: "editing", editing }));
    }
  }, [editing]);

  return { people, online };
}
