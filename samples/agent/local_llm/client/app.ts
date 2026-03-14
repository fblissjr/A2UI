/**
 * A2UI Shell for the local LLM agent.
 *
 * Forked from samples/client/lit/shell/app.ts -- replaces A2A client
 * with a direct fetch-based client. Adds: SSE streaming, new-query flow,
 * dynamic provider badge, text-only fallback.
 */

import { SignalWatcher } from "@lit-labs/signals";
import { provide } from "@lit/context";
import {
  LitElement,
  html,
  css,
  nothing,
  unsafeCSS,
} from "lit";
import { customElement, state } from "lit/decorators.js";
import { repeat } from "lit/directives/repeat.js";
import { v0_8 } from "@a2ui/lit";
import * as UI from "@a2ui/lit/ui";
import { renderMarkdown } from "@a2ui/markdown-it";

import { A2UIClient } from "./client.js";

// Re-export A2UI components so they register
import "@a2ui/lit/ui";

@customElement("a2ui-shell")
export class A2UIShell extends SignalWatcher(LitElement) {
  @provide({ context: UI.Context.theme })
  accessor theme: v0_8.Types.Theme = this.#defaultTheme();

  @provide({ context: UI.Context.markdown })
  accessor markdownRenderer: v0_8.Types.MarkdownRenderer = renderMarkdown;

  @state()
  accessor #requesting = false;

  @state()
  accessor #error: string | null = null;

  @state()
  accessor #hasResults = false;

  @state()
  accessor #loadingTextIndex = 0;

  @state()
  accessor #streamingText = "";

  @state()
  accessor #providerInfo = "connecting...";

  @state()
  accessor #textOnlyResponse = "";

  #loadingInterval: number | undefined;

  #loadingTexts = [
    "Generating UI...",
    "Thinking...",
    "Building components...",
    "Almost there...",
  ];

  static styles = [
    unsafeCSS(v0_8.Styles.structuralStyles),
    css`
      * { box-sizing: border-box; }

      :host {
        display: block;
        max-width: 640px;
        margin: 0 auto;
        min-height: 100%;
        color: light-dark(var(--n-10), var(--n-90));
        font-family: var(--font-family);
      }

      #surfaces {
        width: 100%;
        max-width: 100svw;
        padding: var(--bb-grid-size-3);
        animation: fadeIn 1s cubic-bezier(0, 0, 0.3, 1) 0.3s backwards;
      }

      form {
        display: flex;
        flex-direction: column;
        flex: 1;
        gap: 16px;
        align-items: center;
        padding: 16px 0;
        animation: fadeIn 1s cubic-bezier(0, 0, 0.3, 1) 0.3s backwards;

        & h1 { color: light-dark(var(--p-40), var(--n-90)); }

        & > div {
          display: flex;
          flex: 1;
          gap: 16px;
          align-items: center;
          width: 100%;

          & > input {
            display: block;
            flex: 1;
            border-radius: 32px;
            padding: 16px 24px;
            border: 1px solid var(--p-60);
            background: light-dark(var(--n-100), var(--n-10));
            font-size: 16px;
            color: inherit;
          }

          & > button {
            display: flex;
            align-items: center;
            background: var(--p-40);
            color: var(--n-100);
            border: none;
            padding: 8px 16px;
            border-radius: 32px;
            opacity: 0.5;
            &:not([disabled]) { cursor: pointer; opacity: 1; }
          }
        }
      }

      .pending {
        width: 100%;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        animation: fadeIn 1s cubic-bezier(0, 0, 0.3, 1) 0.3s backwards;
        gap: 16px;
      }

      .spinner {
        width: 48px;
        height: 48px;
        border: 4px solid rgba(255, 255, 255, 0.1);
        border-left-color: var(--p-60);
        border-radius: 50%;
        animation: spin 1s linear infinite;
      }

      .streaming-text {
        max-width: 100%;
        padding: 0 var(--bb-grid-size-4);
        font-size: 14px;
        opacity: 0.7;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 120px;
        overflow-y: auto;
      }

      .theme-toggle {
        padding: 0; margin: 0; border: none;
        display: flex; align-items: center; justify-content: center;
        position: fixed; top: var(--bb-grid-size-3); right: var(--bb-grid-size-4);
        background: light-dark(var(--n-100), var(--n-0));
        border-radius: 50%; color: var(--p-30); cursor: pointer;
        width: 48px; height: 48px; font-size: 32px;
        & .g-icon { pointer-events: none; &::before { content: "dark_mode"; } }
      }

      @container style(--color-scheme: dark) {
        .theme-toggle .g-icon::before { content: "light_mode"; color: var(--n-90); }
      }

      .provider-badge {
        position: fixed; top: var(--bb-grid-size-3); left: var(--bb-grid-size-4);
        background: light-dark(var(--n-100), var(--n-10));
        border: 1px solid var(--p-60);
        border-radius: 16px; padding: 4px 12px;
        font-size: 12px; color: var(--p-40);
      }

      .error {
        color: var(--e-40);
        background-color: var(--e-95);
        border: 1px solid var(--e-80);
        padding: 16px; border-radius: 8px;
        margin: 0 var(--bb-grid-size-3);
      }

      .text-response {
        padding: var(--bb-grid-size-4);
        margin: 0 var(--bb-grid-size-3);
        background: light-dark(var(--n-100), var(--n-10));
        border-radius: 12px;
        line-height: 1.5;
      }

      .follow-up {
        padding: var(--bb-grid-size-3);
        animation: fadeIn 0.5s ease backwards;
      }

      @keyframes spin { to { transform: rotate(360deg); } }
      @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    `,
  ];

  #processor = v0_8.Data.createSignalA2uiMessageProcessor();
  #a2uiClient = new A2UIClient();

  #defaultTheme(): v0_8.Types.Theme {
    return {} as v0_8.Types.Theme;
  }

  connectedCallback() {
    super.connectedCallback();
    // Fetch provider info from server
    this.#a2uiClient.getConfig().then((cfg) => {
      this.#providerInfo = `${cfg.provider} / ${cfg.model}`;
    }).catch(() => {
      this.#providerInfo = "offline";
    });
  }

  render() {
    return [
      this.#renderThemeToggle(),
      this.#renderProviderBadge(),
      this.#maybeRenderForm(),
      this.#maybeRenderData(),
      this.#maybeRenderTextResponse(),
      this.#maybeRenderError(),
      this.#maybeRenderFollowUp(),
    ];
  }

  #renderThemeToggle() {
    return html`<div>
      <button
        @click=${(evt: Event) => {
          if (!(evt.target instanceof HTMLButtonElement)) return;
          const { colorScheme } = window.getComputedStyle(evt.target);
          if (colorScheme === "dark") {
            document.body.classList.add("light");
            document.body.classList.remove("dark");
          } else {
            document.body.classList.add("dark");
            document.body.classList.remove("light");
          }
        }}
        class="theme-toggle"
      >
        <span class="g-icon filled-heavy"></span>
      </button>
    </div>`;
  }

  #renderProviderBadge() {
    return html`<div class="provider-badge">${this.#providerInfo}</div>`;
  }

  #maybeRenderForm() {
    if (this.#requesting) return nothing;
    // Show initial form only before first interaction
    if (this.#hasResults || this.#textOnlyResponse) return nothing;

    return html`<form
      @submit=${(evt: Event) => this.#handleFormSubmit(evt)}
    >
      <h1>A2UI Agent</h1>
      <div>
        <input
          required
          value="Show me a contact card for Alex Chen"
          autocomplete="off"
          id="body"
          name="body"
          type="text"
          ?disabled=${this.#requesting}
        />
        <button type="submit" ?disabled=${this.#requesting}>
          <span class="g-icon filled-heavy">send</span>
        </button>
      </div>
    </form>`;
  }

  #maybeRenderData() {
    if (this.#requesting) {
      const text = this.#loadingTexts[this.#loadingTextIndex];
      return html`<div class="pending">
        <div class="spinner"></div>
        <div class="loading-text">${text}</div>
        ${this.#streamingText
          ? html`<div class="streaming-text">${this.#streamingText}</div>`
          : nothing}
      </div>`;
    }

    const surfaces = this.#processor.getSurfaces();
    if (surfaces.size === 0) return nothing;

    return html`<section id="surfaces">
      ${repeat(
        surfaces,
        ([surfaceId]) => surfaceId,
        ([surfaceId, surface]) => {
          return html`<a2ui-surface
            @a2uiaction=${async (
              evt: v0_8.Events.StateEvent<"a2ui.action">
            ) => {
              const [target] = evt.composedPath();
              if (!(target instanceof HTMLElement)) return;

              const context: v0_8.Types.A2UIClientEventMessage["userAction"]["context"] = {};
              if (evt.detail.action.context) {
                for (const item of evt.detail.action.context) {
                  if (item.value.literalBoolean) {
                    context[item.key] = item.value.literalBoolean;
                  } else if (item.value.literalNumber) {
                    context[item.key] = item.value.literalNumber;
                  } else if (item.value.literalString) {
                    context[item.key] = item.value.literalString;
                  } else if (item.value.path) {
                    const path = this.#processor.resolvePath(
                      item.value.path,
                      evt.detail.dataContextPath
                    );
                    const value = this.#processor.getData(
                      evt.detail.sourceComponent,
                      path,
                      surfaceId
                    );
                    context[item.key] = value;
                  }
                }
              }

              const message: v0_8.Types.A2UIClientEventMessage = {
                userAction: {
                  name: evt.detail.action.name,
                  surfaceId,
                  sourceComponentId: target.id,
                  timestamp: new Date().toISOString(),
                  context,
                },
              };

              await this.#sendAndProcessMessage(message);
            }}
            .surfaceId=${surfaceId}
            .surface=${surface}
            .processor=${this.#processor}
          ></a2ui-surface>`;
        }
      )}
    </section>`;
  }

  #maybeRenderTextResponse() {
    if (!this.#textOnlyResponse || this.#requesting) return nothing;
    return html`<div class="text-response">${this.#textOnlyResponse}</div>`;
  }

  #maybeRenderError() {
    if (!this.#error) return nothing;
    return html`<div class="error">${this.#error}</div>`;
  }

  /** Show a follow-up input after results are displayed. */
  #maybeRenderFollowUp() {
    if (this.#requesting) return nothing;
    if (!this.#hasResults && !this.#textOnlyResponse) return nothing;

    return html`<div class="follow-up">
      <form @submit=${(evt: Event) => this.#handleFormSubmit(evt)}>
        <div>
          <input
            required
            placeholder="Ask something else..."
            autocomplete="off"
            id="body"
            name="body"
            type="text"
            ?disabled=${this.#requesting}
          />
          <button type="submit" ?disabled=${this.#requesting}>
            <span class="g-icon filled-heavy">send</span>
          </button>
        </div>
      </form>
    </div>`;
  }

  #handleFormSubmit(evt: Event) {
    evt.preventDefault();
    if (!(evt.target instanceof HTMLFormElement)) return;
    const data = new FormData(evt.target);
    const body = data.get("body") ?? null;
    if (!body) return;
    evt.target.reset();
    this.#sendAndProcessMessage(body as string);
  }

  async #sendAndProcessMessage(
    message: v0_8.Types.A2UIClientEventMessage | string
  ) {
    try {
      this.#requesting = true;
      this.#error = null;
      this.#textOnlyResponse = "";
      this.#streamingText = "";
      this.#startLoadingAnimation();

      if (typeof message === "string") {
        // Use SSE streaming for text messages
        await this.#sendStreaming(message);
      } else {
        // Use non-streaming for action events
        const messages = await this.#a2uiClient.send(message);
        this.#processResult(messages);
      }
    } catch (err) {
      this.#error = String(err);
      console.error("Send error:", err);
    } finally {
      this.#requesting = false;
      this.#stopLoadingAnimation();
    }
  }

  async #sendStreaming(message: string) {
    return new Promise<void>((resolve) => {
      this.#a2uiClient.sendStream(message, {
        onChunk: (text) => {
          this.#streamingText += text;
        },
        onResult: (data) => {
          if (data.a2ui_messages && data.a2ui_messages.length > 0) {
            this.#processResult(data.a2ui_messages);
          } else if (data.text) {
            // Text-only response (no A2UI components generated)
            this.#textOnlyResponse = data.text;
          }
        },
        onError: (error) => {
          this.#error = error;
        },
        onDone: () => {
          resolve();
        },
      });
    });
  }

  #processResult(messages: v0_8.Types.ServerToClientMessage[]) {
    this.#processor.clearSurfaces();
    this.#processor.processMessages(messages);
    this.#hasResults = true;
  }

  #startLoadingAnimation() {
    this.#loadingTextIndex = 0;
    this.#loadingInterval = window.setInterval(() => {
      this.#loadingTextIndex =
        (this.#loadingTextIndex + 1) % this.#loadingTexts.length;
    }, 2000);
  }

  #stopLoadingAnimation() {
    if (this.#loadingInterval) {
      clearInterval(this.#loadingInterval);
      this.#loadingInterval = undefined;
    }
  }
}
