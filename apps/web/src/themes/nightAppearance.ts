/** 花谷始终保留夜景；各主题的原始色相用于派生界面与花瓣颜色。 */
type RGB = [number, number, number];

function rgb(value: string | undefined, fallback: RGB): RGB {
  const hex = value?.replace(/^#/, '');
  if (!hex || !/^[\da-f]{6}$/i.test(hex)) return fallback;
  return [0, 2, 4].map(
    (offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255,
  ) as RGB;
}

function mix(a: RGB, b: RGB, amount: number): RGB {
  return a.map((value, index) => value + (b[index] - value) * amount) as RGB;
}

function hex(color: RGB): string {
  return (
    '#' +
    color
      .map((value) =>
        Math.round(Math.max(0, Math.min(1, value)) * 255)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  );
}

/** Do not mutate manifests or business state when switching the shared night appearance. */
export function nightAppearance(
  tokens: Record<string, string>,
): Record<string, string> {
  const source = rgb(tokens['--accent'], [0.55, 0.42, 0.6]);
  const background = mix([0.013, 0.016, 0.011], source, 0.012);
  const accent = mix(source, [0.96, 0.93, 0.86], 0.56);
  const surface = mix([0.037, 0.042, 0.032], source, 0.035);
  const raised = mix([0.065, 0.073, 0.053], source, 0.055);
  return {
    ...tokens,
    '--bg': hex(background),
    '--surface': hex(surface),
    '--surface-up': hex(raised),
    '--text': '#f5efe2',
    '--muted': hex(mix([0.72, 0.71, 0.66], source, 0.045)),
    '--accent': hex(accent),
    '--accent-text': hex(accent),
    '--accent-bright': hex(mix(accent, [1, 0.97, 0.9], 0.3)),
    '--accent-ink': '#10120e',
    '--button-bg': hex(accent),
    '--accent-rgb': accent.map((value) => Math.round(value * 255)).join(', '),
    '--scene-secondary': hex(mix(background, source, 0.12)),
    '--border': hex(mix([0.96, 0.93, 0.86], source, 0.1)) + '29',
    '--control-border': hex(mix([0.43, 0.45, 0.39], source, 0.15)),
    '--success': '#a9cf96',
    '--shadow': '0 18px 56px #00000055',
  };
}
