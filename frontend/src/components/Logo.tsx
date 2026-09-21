/**
 * CodeBlack mark and wordmark.
 *
 * The mark is three stacked cargo-container bars; the middle one is short, so
 * the negative space on the right reads as a "C". Pure geometry with no text,
 * no raster images and no external assets, so it stays legible at 16px in a
 * favicon and at 28px in the sidebar.
 *
 * Keep this in sync with public/favicon.svg, which draws the same three bars.
 */

export type LogoTone = "light" | "dark";

/**
 * `tone` is the surface the mark sits ON: "dark" paints it white for the
 * black sidebar, "light" paints it black for light surfaces.
 */
export function LogoMark({
  size = 28,
  tone = "dark",
  className = "",
}: {
  size?: number;
  tone?: LogoTone;
  className?: string;
}) {
  const fill = tone === "dark" ? "var(--color-on-ink)" : "var(--color-ink)";
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      role="img"
      aria-label="CodeBlack"
      className={`shrink-0 ${className}`}
    >
      <rect x="3" y="3" width="26" height="7" rx="1.5" fill={fill} />
      <rect x="3" y="12.5" width="11" height="7" rx="1.5" fill={fill} />
      <rect x="3" y="22" width="26" height="7" rx="1.5" fill={fill} />
    </svg>
  );
}

/** Mark plus the two-line wordmark used in the sidebar and the top bar. */
export function Wordmark({ tone = "dark" }: { tone?: LogoTone }) {
  const title = tone === "dark" ? "text-on-ink" : "text-text";
  const sub = tone === "dark" ? "text-on-ink-muted" : "text-muted";
  return (
    <div className="flex items-start gap-2.5">
      <LogoMark size={28} tone={tone} className="mt-0.5" />
      <div className="min-w-0">
        <p className={`text-md leading-none ${title}`}>
          <span className="font-normal">Code</span>
          <span className="font-bold">Black</span>
        </p>
        {/* Two lines: at 256px the single-line form wraps awkwardly. */}
        <p className={`mt-1.5 text-2xs leading-tight ${sub}`}>
          SDOC
          <br />
          Shipping document verification
        </p>
      </div>
    </div>
  );
}
