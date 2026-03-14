/**
 * Fetch-based A2UI client -- replaces the A2A SDK client with direct
 * HTTP calls to the FastAPI agent at /api/chat and /api/action.
 *
 * Supports both non-streaming (POST /api/chat) and SSE streaming
 * (POST /api/chat/stream) modes.
 */

import { v0_8 } from "@a2ui/lit";

export interface StreamCallbacks {
  onChunk?: (text: string) => void;
  onResult?: (data: {
    text: string;
    a2ui_messages: v0_8.Types.ServerToClientMessage[];
    session_id: string;
  }) => void;
  onError?: (error: string) => void;
  onDone?: () => void;
}

export class A2UIClient {
  #serverUrl: string;
  #sessionId: string | null = null;

  constructor(serverUrl: string = "") {
    this.#serverUrl = serverUrl;
  }

  get sessionId(): string | null {
    return this.#sessionId;
  }

  /** Non-streaming send. */
  async send(
    message: v0_8.Types.A2UIClientEventMessage | string
  ): Promise<v0_8.Types.ServerToClientMessage[]> {
    const isAction = typeof message !== "string" && "userAction" in message;

    const endpoint = isAction ? "/api/action" : "/api/chat";
    const body = isAction
      ? { session_id: this.#sessionId, action: message }
      : { session_id: this.#sessionId, message: message as string };

    const url = this.#serverUrl
      ? `${this.#serverUrl}${endpoint}`
      : endpoint;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Agent error (${res.status}): ${errText}`);
    }

    const data = await res.json();

    if (data.session_id) {
      this.#sessionId = data.session_id;
    }

    return data.a2ui_messages as v0_8.Types.ServerToClientMessage[];
  }

  /** SSE streaming send -- streams text chunks, then final A2UI result. */
  async sendStream(
    message: string,
    callbacks: StreamCallbacks
  ): Promise<void> {
    const url = this.#serverUrl
      ? `${this.#serverUrl}/api/chat/stream`
      : "/api/chat/stream";

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: this.#sessionId,
        message,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      callbacks.onError?.(errText);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      callbacks.onError?.("No response body");
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const lines = buffer.split("\n");
      buffer = lines.pop() || ""; // keep incomplete line

      let currentEvent = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const rawData = line.slice(6);

          if (currentEvent === "chunk") {
            try {
              const parsed = JSON.parse(rawData);
              callbacks.onChunk?.(parsed.text);
            } catch { /* skip malformed */ }
          } else if (currentEvent === "result") {
            try {
              const parsed = JSON.parse(rawData);
              if (parsed.session_id) {
                this.#sessionId = parsed.session_id;
              }
              callbacks.onResult?.(parsed);
            } catch { /* skip malformed */ }
          } else if (currentEvent === "error") {
            try {
              const parsed = JSON.parse(rawData);
              callbacks.onError?.(parsed.error);
            } catch { /* skip malformed */ }
          } else if (currentEvent === "done") {
            callbacks.onDone?.();
          }

          currentEvent = "";
        }
      }
    }

    callbacks.onDone?.();
  }

  /** Fetch current provider config from the server. */
  async getConfig(): Promise<{ provider: string; model: string }> {
    const url = this.#serverUrl
      ? `${this.#serverUrl}/api/config`
      : "/api/config";

    const res = await fetch(url);
    return res.json();
  }
}
