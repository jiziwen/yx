/** 原版花谷引擎的本地资源、动态偏好与宿主页面集成验收。 */
import { test, expect, type Page } from "@playwright/test";

const originalAssets = "/flower-valley/";
const frameSelector = "iframe.flower-valley-frame";

// Keep the original compact preset for software WebGL, without modifying it.
test.use({ viewport: { width: 1100, height: 580 } });
test.setTimeout(90000);
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    sessionStorage.setItem("yingxu-intro", "seen"),
  );
});

async function readyGarden(
  page: Page,
  motion: "reduce" | "no-preference" = "reduce",
) {
  await page.emulateMedia({ reducedMotion: motion });
  await page.goto("/");
  const frame = page.locator(frameSelector);
  await expect(page.locator(".flower-valley")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 45000 },
  );
  await expect(frame).toHaveCSS("opacity", "1");
  const scene = page.frameLocator(frameSelector);
  await expect(scene.locator("html")).toHaveAttribute("data-state", "ready");
  const canvas = scene.locator(".js-canvas-container canvas");
  await expect(canvas).toBeVisible();
  return { frame, scene, canvas };
}

/** Foreground UI overlaps iframe screenshots; hide it only while comparing pixels. */
async function withSceneOnly<T>(
  page: Page,
  capture: () => Promise<T>,
): Promise<T> {
  const style = await page.addStyleTag({
    content: `
    .dream-preview > :not(.flower-valley),
    .dream-preview > :not(.flower-valley) *,
    .flower-valley-paper, .flower-valley-fallback { visibility: hidden !important; }
  `,
  });
  try {
    return await capture();
  } finally {
    await style.evaluate((node) => node.parentNode?.removeChild(node));
  }
}

function rgbChannels(color: string): number[] {
  const channels = color
    .match(/[\d.]+/g)
    ?.slice(0, 3)
    .map(Number);
  if (!channels || channels.length !== 3)
    throw new Error(`无法解析颜色：${color}`);
  return channels;
}
function luminance(channels: number[]): number {
  const linear = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

test("本地原版引擎、相机路径与图集加载成功并绘制 WebGL 花谷", async ({
  page,
}, testInfo) => {
  const loaded = new Set<string>();
  const failures: string[] = [];
  const errors: string[] = [];
  const remote: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith(originalAssets)) return;
    loaded.add(url.pathname.slice(originalAssets.length));
    if (!response.ok()) failures.push(`${response.status()} ${url.pathname}`);
  });
  page.on("request", (request) => {
    if (/gladeye\.com|motionsites\.ai/.test(request.url()))
      remote.push(request.url());
  });
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).pathname.startsWith(originalAssets))
      failures.push(request.url());
  });
  const { frame, canvas } = await readyGarden(page);
  expect([...loaded]).toEqual(
    expect.arrayContaining([
      "runtime.js",
      "vendor.js",
      "scene.js",
      "valley/camera-path07.glb",
      "valley/terrain.png",
      "valley/flowers/pool_summer.png",
      "valley/flowers/pool_winter.png",
    ]),
  );
  expect(failures).toEqual([]);
  expect(remote).toEqual([]);
  expect(errors).toEqual([]);
  expect(
    await canvas.evaluate((node) => {
      const canvas = node as HTMLCanvasElement;
      const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
      return {
        available: !!gl,
        lost: gl?.isContextLost(),
        error: gl?.getError(),
      };
    }),
  ).toEqual({ available: true, lost: false, error: 0 });
  await expect(frame).toHaveAttribute("src", "/flower-valley/index.html");
  await withSceneOnly(page, async () => {
    await testInfo.attach("原版花谷静帧", {
      body: await canvas.screenshot(),
      contentType: "image/png",
    });
  });
});

test("正常动态推进真实像素，减少动态偏好暂停场景并可恢复", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 640, height: 480 });
  const { canvas } = await readyGarden(page, "no-preference");
  await withSceneOnly(page, async () => {
    const first = await canvas.screenshot();
    await expect
      .poll(async () => first.equals(await canvas.screenshot()), {
        timeout: 20000,
      })
      .toBe(false);
    await testInfo.attach("原版动态首帧", {
      body: first,
      contentType: "image/png",
    });
    await page.emulateMedia({ reducedMotion: "reduce" });
    // Preference messages cross documents; wait for delivery before comparing.
    await page.waitForTimeout(300);
    const still = await canvas.screenshot();
    await page.waitForTimeout(350);
    expect(still.equals(await canvas.screenshot())).toBe(true);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expect
      .poll(async () => still.equals(await canvas.screenshot()), {
        timeout: 20000,
      })
      .toBe(false);
  });
});

test("六主题只更新配色，保留原版场景实例与创作输入", async ({ page }) => {
  const { frame, canvas } = await readyGarden(page);
  const originalFrame = await frame.elementHandle();
  const originalCanvas = await canvas.elementHandle();
  const input = page.getByLabel("告诉 Lumi 你的拍摄想法");
  const originalInput = await input.elementHandle();
  if (!originalFrame || !originalCanvas || !originalInput)
    throw new Error("场景或输入不存在");
  const brief = "切换主题时，保留这个花谷与我的拍摄想法。";
  await input.fill(brief);
  await withSceneOnly(page, async () => {
    const first = await canvas.screenshot();
    await page.waitForTimeout(350);
    expect(first.equals(await canvas.screenshot())).toBe(true);
  });
  const themes = [
    ["rose", "玫瑰画廊"],
    ["film", "绯红剧场"],
    ["portrait", "雾光艺廊"],
    ["fresh", "晴日来信"],
    ["coast", "海岛叙事"],
    ["oriental", "东方喜事"],
  ];
  const colors = new Set<string>();
  const filters = new Set<string>();
  for (const [id, name] of themes) {
    await page
      .locator(".at-theme-strip")
      .getByRole("button", { name: `切换主题：${name}`, exact: true })
      .click();
    await expect(page.locator(".studio-theme")).toHaveAttribute(
      "data-style",
      id,
    );
    await expect(input).toHaveValue(brief);
    expect(
      await input.evaluate(
        (node, original) => node === original,
        originalInput,
      ),
    ).toBe(true);
    expect(
      await frame.evaluate(
        (node, original) => node === original,
        originalFrame,
      ),
    ).toBe(true);
    expect(
      await canvas.evaluate(
        (node, original) => node === original,
        originalCanvas,
      ),
    ).toBe(true);
    await expect(page.locator(".flower-valley")).toHaveAttribute(
      "data-ready",
      "true",
    );
    const appearance = await page.locator(".studio-theme").evaluate((node) => {
      const style = getComputedStyle(node);
      const garden = node.querySelector(".flower-valley");
      const frame = node.querySelector("iframe.flower-valley-frame");
      if (!garden || !frame) throw new Error("主题内场景不存在");
      return {
        background: style.backgroundColor,
        text: style.color,
        colorScheme: style.colorScheme,
        gardenBackground: getComputedStyle(garden)
          .getPropertyValue("--fv-bg")
          .trim(),
        primary: getComputedStyle(garden)
          .getPropertyValue("--fv-primary")
          .trim(),
        filter: getComputedStyle(frame).filter,
      };
    });
    expect(appearance.colorScheme).toBe("dark");
    const background = rgbChannels(appearance.background);
    for (const value of [
      ...background,
      ...rgbChannels(appearance.gardenBackground),
    ])
      expect(value).toBeLessThan(30);
    expect(
      (luminance(rgbChannels(appearance.text)) + 0.05) /
        (luminance(background) + 0.05),
    ).toBeGreaterThanOrEqual(4.5);
    colors.add(appearance.primary);
    filters.add(appearance.filter);
  }
  expect(colors.size).toBe(6);
  expect(filters.size).toBeGreaterThan(1);
  await originalInput.dispose();
  await originalCanvas.dispose();
  await originalFrame.dispose();
});

test("上下文丢失显示回退，恢复后保留同一场景和输入", async ({ page }) => {
  const { canvas, frame } = await readyGarden(page);
  const originalFrame = await frame.elementHandle();
  const originalCanvas = await canvas.elementHandle();
  const extension = await canvas.evaluateHandle((node) => {
    const canvas = node as HTMLCanvasElement;
    return (
      (canvas.getContext("webgl2") || canvas.getContext("webgl"))?.getExtension(
        "WEBGL_lose_context",
      ) ?? null
    );
  });
  test.skip(
    await extension.evaluate((value) => value === null),
    "驱动不提供上下文测试扩展",
  );
  const input = page.getByLabel("告诉 Lumi 你的拍摄想法");
  await input.fill("恢复场景后继续保留的拍摄想法。");
  await extension.evaluate((value) => value?.loseContext());
  await expect(page.locator(".flower-valley")).toHaveAttribute(
    "data-ready",
    "false",
  );
  await expect(page.locator(".flower-valley-fallback")).toHaveCSS(
    "opacity",
    "1",
  );
  await expect(input).toHaveValue("恢复场景后继续保留的拍摄想法。");
  await extension.evaluate((value) => value?.restoreContext());
  await expect(page.locator(".flower-valley")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 45000 },
  );
  expect(
    await frame.evaluate((node, original) => node === original, originalFrame),
  ).toBe(true);
  expect(
    await canvas.evaluate(
      (node, original) => node === original,
      originalCanvas,
    ),
  ).toBe(true);
  expect(
    await canvas.evaluate((node) => {
      const canvas = node as HTMLCanvasElement;
      return (
        canvas.getContext("webgl2") || canvas.getContext("webgl")
      )?.isContextLost();
    }),
  ).toBe(false);
  await expect(input).toHaveValue("恢复场景后继续保留的拍摄想法。");
  await extension.dispose();
  await originalCanvas?.dispose();
  await originalFrame?.dispose();
});

test("窄屏适配视口，背景不拦截输入或产生横向滚动", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { canvas, frame } = await readyGarden(page);
  expect(
    await frame.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        overflow: document.documentElement.scrollWidth > innerWidth,
        pointerEvents: getComputedStyle(node).pointerEvents,
        tabIndex: (node as HTMLIFrameElement).tabIndex,
      };
    }),
  ).toEqual({
    x: 0,
    y: 0,
    width: 390,
    height: 844,
    overflow: false,
    pointerEvents: "none",
    tabIndex: -1,
  });
  expect(
    await canvas.evaluate((node) => ({
      width: node.getBoundingClientRect().width,
      height: node.getBoundingClientRect().height,
    })),
  ).toEqual({ width: 390, height: 844 });
  const input = page.getByLabel("告诉 Lumi 你的拍摄想法");
  await input.fill("窄屏也可以在原版花谷里写下灵感。");
  await expect(input).toHaveValue("窄屏也可以在原版花谷里写下灵感。");
  await testInfo.attach("窄屏原版花谷", {
    body: await page.screenshot(),
    contentType: "image/png",
  });
  await page.setViewportSize({ width: 430, height: 932 });
  await expect
    .poll(() => canvas.evaluate((node) => node.getBoundingClientRect().width))
    .toBe(430);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("鼠标与滚轮转发到原版场景，同时保留页面输入和滚动", async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 480 });
  const { scene } = await readyGarden(page, "no-preference");
  // Observe document messages rather than modifying engine internals.
  await scene.locator("html").evaluate((node) => {
    window.addEventListener("message", (event) => {
      if (event.data?.channel !== "yingxu:original-flower-valley") return;
      if (event.data.action === "pointer")
        node.setAttribute(
          "data-test-pointer",
          JSON.stringify([event.data.x, event.data.y]),
        );
      if (event.data.action === "wheel")
        node.setAttribute("data-test-wheel", String(event.data.deltaY));
    });
  });
  await page.mouse.move(320, 240);
  await expect(scene.locator("html")).toHaveAttribute(
    "data-test-pointer",
    "[0.5,0.5]",
  );
  await page.mouse.wheel(0, 300);
  await expect(scene.locator("html")).toHaveAttribute("data-test-wheel", "300");
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  const input = page.getByLabel("告诉 Lumi 你的拍摄想法");
  await input.fill("鼠标经过花谷后仍能正常写下灵感。");
  await expect(input).toHaveValue("鼠标经过花谷后仍能正常写下灵感。");
});

test("原版素材失败时保留静态花谷和表单，重新加载恢复", async ({ page }) => {
  await page.route("**/flower-valley/valley/terrain.png", (route) =>
    route.fulfill({ status: 503, body: "fixture unavailable" }),
  );
  await page.goto("/");
  const frame = page.frameLocator(frameSelector);
  await expect(frame.locator(".js-canvas-container canvas")).toBeAttached();
  await expect(page.locator(".flower-valley")).toHaveAttribute(
    "data-ready",
    "false",
  );
  await expect(page.locator(".flower-valley-fallback")).toHaveCSS(
    "opacity",
    "1",
  );
  const input = page.getByLabel("告诉 Lumi 你的拍摄想法");
  await input.fill("资源失败时仍可以输入。");
  await expect(input).toHaveValue("资源失败时仍可以输入。");
  await page.unroute("**/flower-valley/valley/terrain.png");
  await readyGarden(page);
});
