import { LitElement, html } from "lit";
import { customElement } from "lit/decorators.js";
import { assetUrl } from "../../core/AssetUrls";
import "./CosmeticBackground";
import "./NewsBox";
import "./StreamingNow";

@customElement("play-page")
export class PlayPage extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <div
        id="page-play"
        class="flex flex-col gap-1 w-full px-0 lg:px-4 min-h-0"
      >
        <token-login class="absolute"></token-login>

        <!-- Mobile: Fixed top bar -->
        <div
          class="lg:hidden fixed left-0 right-0 top-0 z-40 pt-[env(safe-area-inset-top)] bg-surface border-b border-white/10"
        >
          <div
            class="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center h-14 px-2 gap-2"
          >
            <button
              id="hamburger-btn"
              class="col-start-1 justify-self-start h-10 shrink-0 aspect-[4/3] flex text-white/90 rounded-md items-center justify-center transition-colors"
              data-i18n-aria-label="main.menu"
              aria-expanded="false"
              aria-controls="sidebar-menu"
              aria-haspopup="dialog"
              data-i18n-title="main.menu"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke-width="1.5"
                stroke="currentColor"
                class="size-8"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
                />
              </svg>
            </button>

            <div
              class="col-start-2 flex items-center justify-center text-malibu-blue min-w-0"
            >
              <img
                src=${assetUrl("images/OpenFrontLogo.svg")}
                alt="OpenFront"
                class="h-full w-auto"
              />
            </div>

            <div
              aria-hidden="true"
              class="col-start-3 justify-self-end h-10 shrink-0 aspect-[4/3]"
            ></div>
          </div>
        </div>

        <!-- Mobile: spacer for the fixed top bar. Kept out of the grid so it never
             occupies a column. -->
        <div
          class="lg:hidden h-[calc(env(safe-area-inset-top)+56px)] -mb-1"
        ></div>

        <!-- Top strip. Mirrors game-mode-selector's grid (sm:2fr/1fr, same bounds and gap)
             so the Streaming Now panel lines up exactly with the game lobby column below. -->
        <div
          class="w-full pb-4 sm:pb-0 flex flex-col gap-4 sm:grid sm:grid-cols-[2fr_1fr] sm:gap-4 sm:items-stretch"
        >
          <!-- Left column: news banner + identity row, stacked tight so the row sits
               directly under the banner. -->
          <div class="flex flex-col gap-2 min-w-0">
            <news-box></news-box>

            <!-- Identity row: flag + tag/username + skin in one line. Flag sits before the
                 tag (where it shows in-game), skin at the end; both preview the current
                 selection. Replaces the old separate SELECT SKIN / SELECT FLAG buttons. -->
            <div
              class="relative bg-surface border-y border-white/10 overflow-visible flex items-center sm:min-h-[60px] sm:flex-1 sm:z-20 sm:border-y-0 sm:rounded-xl"
            >
              <!-- Selected skin/pattern fills the bubble like the player's territory in
                   game (the skin button updates it), shown as a frame around the controls. -->
              <cosmetic-background
                class="absolute inset-0 z-0 overflow-hidden sm:rounded-xl pointer-events-none"
              ></cosmetic-background>
              <!-- Controls share one surface bubble so it reads as a single clean bar
                   (buttons are the same surface color, so they blend at rest and only
                   highlight on hover), not three separate chips. -->
              <div
                class="relative z-10 flex h-full w-full min-w-0 items-center gap-2 bg-surface/80 p-1 sm:rounded-xl"
              >
                <!-- Flag + skin fill the bubble height (minus the 1-unit padding) so they
                     hug the edges, capped so they never blow up if the bubble stretches. -->
                <flag-input
                  show-select-label
                  class="shrink-0 h-full max-h-[52px] aspect-square"
                ></flag-input>
                <username-input
                  class="flex-1 min-w-0 h-10 sm:h-[50px]"
                ></username-input>
                <!-- Raised 3D shadow so the skin pops off the bar and is easy to spot. -->
                <pattern-input
                  show-select-label
                  class="shrink-0 h-full max-h-[52px] aspect-square rounded-lg [box-shadow:0_3px_6px_#00000099,0_1px_2px_#000000cc]"
                ></pattern-input>
              </div>
            </div>
          </div>

          <!-- Right column: Streaming Now, stretched to the left column's full height
               (news + identity) so the top strip has no dead space. -->
          <streaming-now
            class="w-full min-w-0 sm:h-full sm:flex sm:flex-col"
          ></streaming-now>
        </div>

        <game-mode-selector></game-mode-selector>
      </div>
    `;
  }
}
