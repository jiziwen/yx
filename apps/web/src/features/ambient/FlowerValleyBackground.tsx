/** Host the original scene in its own document without remounting the application. */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useTheme } from "../../themes/ThemeProvider";
import { flowerCssColor, flowerPalette } from "./palette";
import "./flower-valley.css";

const CHANNEL = "yingxu:original-flower-valley";
const SCENE_URL = "/flower-valley/index.html";
const THEME_HUE: Record<string, number> = {
  rose: -6,
  film: -3,
  portrait: 4,
  fresh: -10,
  coast: 0,
  oriental: 7,
};
type SceneState = "loading" | "ready" | "error";
type SceneCommand =
  | { action: "state"; active: boolean; reduced: boolean }
  | { action: "status" | "resize" }
  | { action: "pointer"; x: number; y: number }
  | { action: "wheel"; deltaX: number; deltaY: number; deltaMode: number };

export default function FlowerValleyBackground({
  subtle = false,
}: {
  subtle?: boolean;
}) {
  const { theme } = useTheme();
  const palette = useMemo(() => flowerPalette(theme.tokens), [theme.tokens]);
  const frame = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<SceneState>("loading");

  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const origin = window.location.origin;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let disposed = false;
    let pointerFrame = 0;
    let pendingPointer: { x: number; y: number } | null = null;
    const post = (command: SceneCommand) => {
      if (!disposed)
        element.contentWindow?.postMessage(
          { channel: CHANNEL, ...command },
          origin,
        );
    };
    const syncState = () => {
      post({
        action: "state",
        active: !document.hidden,
        reduced: motion.matches,
      });
      if (document.hidden || motion.matches) {
        cancelAnimationFrame(pointerFrame);
        pointerFrame = 0;
        pendingPointer = null;
      }
    };
    const onResize = () => post({ action: "resize" });
    const requestStatus = () => {
      syncState();
      post({ action: "status" });
      onResize();
    };
    const onLoad = () => {
      setState("loading");
      requestStatus();
    };
    const onError = () => setState("error");
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.origin !== origin || event.source !== element.contentWindow)
        return;
      if (!event.data || typeof event.data !== "object") return;
      const data = event.data as { channel?: unknown; state?: unknown };
      if (data.channel !== CHANNEL) return;
      if (
        data.state === "loading" ||
        data.state === "ready" ||
        data.state === "error"
      ) {
        setState(data.state);
        if (data.state === "ready") syncState();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (document.hidden || motion.matches) return;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pendingPointer = {
        x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
        y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
      };
      if (pointerFrame) return;
      pointerFrame = requestAnimationFrame(() => {
        pointerFrame = 0;
        const pointer = pendingPointer;
        pendingPointer = null;
        if (pointer && !document.hidden && !motion.matches)
          post({ action: "pointer", ...pointer });
      });
    };
    const onWheel = (event: WheelEvent) => {
      if (document.hidden || motion.matches) return;
      post({
        action: "wheel",
        deltaX: event.deltaX,
        deltaY: event.deltaY,
        deltaMode: event.deltaMode,
      });
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("resize", onResize, { passive: true });
    document.addEventListener("visibilitychange", syncState);
    motion.addEventListener("change", syncState);
    element.addEventListener("load", onLoad);
    element.addEventListener("error", onError);
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(onResize);
    observer?.observe(element);
    // Covers a cached document that completed loading before React's effect.
    requestStatus();

    return () => {
      disposed = true;
      observer?.disconnect();
      cancelAnimationFrame(pointerFrame);
      pendingPointer = null;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", syncState);
      motion.removeEventListener("change", syncState);
      element.removeEventListener("load", onLoad);
      element.removeEventListener("error", onError);
      // Actual DOM removal tears down the iframe document and its GPU resources.
      // Leaving src intact also supports StrictMode's simulated effect cleanup.
    };
  }, []);

  const style = {
    "--fv-bg": flowerCssColor(palette.background),
    "--fv-primary": flowerCssColor(palette.primary),
    "--fv-secondary": flowerCssColor(palette.secondary),
    "--fv-foliage": flowerCssColor(palette.foliage),
    "--fv-glow": flowerCssColor(palette.glow),
    "--fv-hue": `${THEME_HUE[theme.id] ?? 0}deg`,
  } as CSSProperties;

  return (
    <div
      className="flower-valley"
      data-state={state}
      data-ready={state === "ready"}
      data-subtle={subtle}
      data-dark={palette.dark}
      style={style}
      aria-hidden="true"
    >
      <div className="flower-valley-fallback" />
      <iframe
        ref={frame}
        src={SCENE_URL}
        className="flower-valley-frame"
        title="Flower Valley 原版花谷动态背景"
        tabIndex={-1}
        aria-hidden="true"
      />
      <div className="flower-valley-paper" />
    </div>
  );
}
