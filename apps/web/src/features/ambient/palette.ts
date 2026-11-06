/** sRGB 0–1 colours consumed by the flower valley renderer. */
import { nightAppearance } from '../../themes/nightAppearance';
type RGB = [number, number, number];

export interface FlowerPalette {
  background: RGB;
  primary: RGB;
  secondary: RGB;
  foliage: RGB;
  glow: RGB;
  dark: boolean;
}

function readHex(value: string | undefined, fallback: RGB): RGB {
  if (!value) return fallback;
  const hex = value.trim().replace(/^#/, '');
  const expanded =
    hex.length === 3 ? hex.replace(/./g, (digit) => digit + digit) : hex;
  if (!/^[\da-f]{6}$/i.test(expanded)) return fallback;
  return [0, 2, 4].map(
    (offset) => parseInt(expanded.slice(offset, offset + 2), 16) / 255,
  ) as RGB;
}

function mix(a: RGB, b: RGB, amount: number): RGB {
  return a.map((value, index) => value + (b[index] - value) * amount) as RGB;
}

function luminance(color: RGB): number {
  const linear = color.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

/** Keep the theme's petal hue luminous against the night valley. */
function petal(color: RGB, dark: boolean): RGB {
  const high = Math.max(...color);
  const low = Math.min(...color);
  if (high - low < 0.035) return mix(color, [0.76, 0.47, 0.64], 0.38);
  const middle = (high + low) / 2;
  const saturated = color.map((value) =>
    Math.max(0, Math.min(1, middle + (value - middle) * 1.45)),
  ) as RGB;
  return mix(
    saturated,
    dark ? [1, 0.88, 0.82] : [0.25, 0.17, 0.25],
    dark ? 0.18 : 0.13,
  );
}

/** New theme plugins inherit their scene without maintaining a separate ID lookup table. */
export function flowerPalette(tokens: Record<string, string>): FlowerPalette {
  const background = readHex(
    nightAppearance(tokens)['--bg'],
    [0.015, 0.018, 0.012],
  );
  const accent = readHex(tokens['--accent'], [0.55, 0.42, 0.6]);
  const scene = readHex(tokens['--scene-secondary'], [0.9, 0.84, 0.94]);
  const dark = luminance(background) < 0.25;
  return {
    background,
    primary: petal(accent, dark),
    secondary: petal(mix(scene, accent, 0.32), dark),
    foliage: mix([0.2, 0.36, 0.27], accent, 0.2),
    glow: mix([1, 0.88, 0.57], scene, 0.18),
    dark,
  };
}

export function flowerCssColor(color: RGB): string {
  return `rgb(${color.map((value) => Math.round(value * 255)).join(' ')})`;
}
