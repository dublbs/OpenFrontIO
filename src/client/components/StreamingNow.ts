import { LitElement, html, nothing } from "lit";
import { customElement, state } from "lit/decorators.js";
import type { LiveStream } from "../../core/ApiSchemas";
import { getLiveStreams } from "../Api";
import { translateText } from "../Utils";

const REFRESH_MS = 90_000; // re-fetch the served list so counts/liveness stay fresh
const MAX_VISIBLE = 5; // keep the panel compact; link to the category for the rest
const CATEGORY_URL = "https://www.twitch.tv/directory/category/openfront";

// Watch URL for a stream: explicit `url` wins, else derive from platform + channel.
export function watchUrl(s: LiveStream): string {
  if (s.url) return s.url;
  return s.platform === "youtube"
    ? `https://www.youtube.com/${s.channel}`
    : `https://www.twitch.tv/${s.channel}`;
}

// Compact viewer count: 932 -> "932", 1234 -> "1.2K", 12345 -> "12K", 1.2e6 -> "1.2M".
export function formatViewers(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) {
    const k = n / 1000;
    if (k >= 999.5) return "1.0M"; // avoid "1000K" when rounding crosses a million
    return `${k.toFixed(k < 9.95 ? 1 : 0)}K`;
  }
  return `${(n / 1_000_000).toFixed(1)}M`;
}

// Homepage "Streaming Now" panel: a compact list of who is live playing OpenFront, fed by
// getLiveStreams() (served JSON + bundled fallback). Stays hidden until it has live streams,
// so the sibling news box keeps the full row when nobody is live (the common case).
@customElement("streaming-now")
export class StreamingNow extends LitElement {
  @state() private streams: LiveStream[] = [];
  private refreshTimer: ReturnType<typeof setInterval> | null = null;
  private loadGen = 0; // ignore a stale fetch that resolves after a newer one

  // Light DOM so Tailwind classes apply (matches NewsBox).
  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this.style.display = "none"; // hidden until the first load finds a live stream (no flash)
    void this.load();
    this.refreshTimer = setInterval(() => void this.load(), REFRESH_MS);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = null;
  }

  private async load() {
    const gen = ++this.loadGen;
    const cfg = await getLiveStreams();
    if (gen !== this.loadGen) return; // superseded by a newer load()
    const streams = cfg.enabled ? cfg.streams : [];
    // Highest viewer counts first (defensive; the backend already sorts).
    this.streams = [...streams].sort((a, b) => b.viewers - a.viewers);
    // Collapse the host so the sibling news box takes the full row when nobody is live.
    this.style.display = this.streams.length === 0 ? "none" : "";
  }

  render() {
    if (this.streams.length === 0) return nothing;
    const shown = this.streams.slice(0, MAX_VISIBLE);
    // The "more" link goes to the Twitch category, so only count hidden Twitch streams.
    const extra = this.streams
      .slice(MAX_VISIBLE)
      .filter((s) => s.platform === "twitch").length;
    const count = translateText("streaming_now.live_count", {
      count: this.streams.length,
    });
    return html`
      <div
        class="flex h-full flex-col bg-surface px-2 py-2 border-y border-white/10 lg:border-y-0 lg:rounded-xl lg:p-3"
      >
        <div class="mb-2 flex items-center gap-2">
          <span class="h-2 w-2 animate-pulse rounded-full bg-red-500"></span>
          <span
            class="text-xs font-bold uppercase tracking-wider text-white/70"
          >
            ${translateText("streaming_now.title")}
          </span>
          <span
            class="ml-auto text-[11px] text-white/40"
            title="${count}"
            aria-label="${count}"
            >${this.streams.length}</span
          >
        </div>
        <div class="flex flex-col gap-1.5">
          ${shown.map((s) => this.renderRow(s))}
        </div>
        ${extra > 0
          ? html`<a
              href="${CATEGORY_URL}"
              target="_blank"
              rel="noopener noreferrer"
              class="mt-2 text-[11px] text-white/50 transition-colors hover:text-blue-300"
              >${translateText("streaming_now.more", { count: extra })}</a
            >`
          : nothing}
      </div>
    `;
  }

  private renderRow(s: LiveStream) {
    return html`
      <a
        href="${watchUrl(s)}"
        target="_blank"
        rel="noopener noreferrer"
        title="${s.title ?? nothing}"
        aria-label="${translateText("streaming_now.watch", {
          name: s.displayName,
        })}"
        class="group flex items-center gap-2 rounded-lg p-1 transition-colors hover:bg-white/5"
      >
        ${s.avatarUrl
          ? html`<img
              src="${s.avatarUrl}"
              alt=""
              loading="lazy"
              referrerpolicy="no-referrer"
              class="h-8 w-8 shrink-0 rounded-full object-cover"
            />`
          : html`<div class="h-8 w-8 shrink-0 rounded-full bg-white/10"></div>`}
        <div class="min-w-0 flex-1">
          <div
            class="truncate text-sm font-medium text-white transition-colors group-hover:text-blue-300"
          >
            ${s.displayName}
          </div>
          <div class="flex items-center gap-1 text-xs text-white/50">
            <span class="h-1.5 w-1.5 rounded-full bg-red-500"></span>
            ${translateText("streaming_now.viewers", {
              count: formatViewers(s.viewers),
            })}
          </div>
        </div>
        ${this.platformIcon(s.platform)}
      </a>
    `;
  }

  private platformIcon(platform: LiveStream["platform"]) {
    const cls = "mt-0.5 h-3.5 w-3.5 shrink-0 self-start";
    if (platform === "youtube") {
      return html`<svg
        viewBox="0 0 24 24"
        fill="currentColor"
        class="${cls} text-red-500"
      >
        <path
          d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"
        />
      </svg>`;
    }
    return html`<svg
      viewBox="0 0 24 24"
      fill="currentColor"
      class="${cls} text-[#9146FF]"
    >
      <path
        d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
      />
    </svg>`;
  }
}
