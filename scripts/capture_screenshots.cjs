// Reproducible README screenshots from the local production build.
// Requires NODE_PATH to contain Playwright and LECTORA_SESSION_COOKIE to be set.
const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = process.env.LECTORA_BASE_URL || "http://127.0.0.1:8000";
const sessionCookie = process.env.LECTORA_SESSION_COOKIE;
if (!sessionCookie) throw new Error("Set LECTORA_SESSION_COOKIE before capturing screenshots");

const output = path.resolve(__dirname, "..", "docs", "screenshots");
const lectureId = process.env.LECTORA_SCREENSHOT_LECTURE || "485f670c-c367-4994-b11a-dbe9b3fae1d3";

async function settle(page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1400);
}

async function capture(page, file) {
  await page.screenshot({ path: path.join(output, file), fullPage: false });
  console.log(`Captured ${file}`);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.LECTORA_CHROMIUM_PATH || chromium.executablePath(),
  });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
    locale: "ru-RU",
  });
  await context.addCookies([{ name: "session", value: sessionCookie, url: baseUrl }]);
  await context.addInitScript(() => {
    localStorage.setItem("lectora.theme", "dark");
    localStorage.setItem("lectora-llm-mode", "api");
    localStorage.setItem("lectora-use-gpu", "true");
  });
  const page = await context.newPage();

  await page.goto(`${baseUrl}/`);
  await settle(page);
  await capture(page, "01-library.png");

  await page.locator(".header__actions .btn--primary").click();
  await page.locator(".modal").waitFor({ state: "visible" });
  const accessSelects = page.locator(".upload-access-grid select");
  await accessSelects.nth(2).selectOption("en");
  await accessSelects.nth(3).selectOption("ru");
  await page.locator(".gpu-option").filter({ hasText: "Русская озвучка" }).locator('input[type="checkbox"]').check({ force: true });
  await page.waitForTimeout(700);
  await capture(page, "02-upload-translation.png");
  await page.getByRole("button", { name: "Закрыть" }).click().catch(() => page.keyboard.press("Escape"));

  await page.goto(`${baseUrl}/lectures/${lectureId}`);
  await settle(page);
  await page.getByRole("button", { name: "Поиск", exact: true }).click();
  const search = page.getByPlaceholder("Искать по смыслу внутри лекции…");
  await search.fill("практика английского языка");
  await search.press("Enter");
  await page.locator(".results-meta").waitFor({ state: "visible", timeout: 120000 });
  await capture(page, "03-lecture-search.png");

  await page.goto(`${baseUrl}/public`);
  await settle(page);
  await capture(page, "04-public-library.png");

  await page.goto(`${baseUrl}/account`);
  await settle(page);
  await capture(page, "05-account-groups.png");

  await page.goto(`${baseUrl}/lectures/${lectureId}`);
  await settle(page);
  await page.locator(".player-settings__toggle").click();
  await page.locator(".player-settings__menu").waitFor({ state: "visible" });
  await capture(page, "06-player-subtitles.png");

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
