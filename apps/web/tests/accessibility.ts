import { expect, type Page } from "@playwright/test";

// Check actual painted text (including muted opacity), names and native tab order.
// Screenshots are still reviewed by a person; this is not a screen-reader audit.
export async function accessibility(page: Page, keyboard = true) {
  const failures = await page.evaluate(() => {
    const issues: string[] = [];
    const visible = (el: Element) => el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    for (const el of document.querySelectorAll<HTMLElement>("button, a, input, select, textarea, summary")) {
      if (!visible(el)) continue;
      const labels = "labels" in el ? (el as HTMLInputElement).labels : null;
      if (!(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || labels?.length || el.textContent?.trim())) issues.push(`Missing name: ${el.tagName}`);
      if (el.tabIndex > 0) issues.push("Positive tab index");
    }
    for (const el of document.querySelectorAll("img")) if (!el.alt) issues.push("Missing image alternative");
    const rgb = (s: string) => s.match(/[\d.]+/g)!.slice(0, 3).map(Number);
    const luminance = (channels: number[]) => channels.map(c => c / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
    for (const el of document.querySelectorAll<HTMLElement>("p, h1, h2, h3, label, button, a, summary, li, input, select, textarea")) {
      if (!visible(el) || el.matches(":disabled") || !el.textContent?.trim() && !el.matches("input, textarea")) continue;
      let parent: Element | null = el;
      let background = "";
      let opacity = 1;
      while (parent) {
        const style = getComputedStyle(parent);
        opacity *= Number(style.opacity);
        if (!background && style.backgroundColor !== "rgba(0, 0, 0, 0)") background = style.backgroundColor;
        parent = parent.parentElement;
      }
      const back = rgb(background), style = getComputedStyle(el);
      const foreground = rgb(style.color).map((c, i) => c * opacity + back[i] * (1 - opacity));
      const values = [luminance(foreground), luminance(back)].sort((a, b) => b - a);
      const ratio = (values[0] + .05) / (values[1] + .05);
      const large = parseFloat(style.fontSize) >= 24 || parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700;
      if (ratio < (large ? 3 : 4.5)) issues.push(`${el.tagName}: ${el.textContent?.slice(0, 55)} contrast ${ratio.toFixed(2)}`);
    }
    return issues;
  });
  expect(failures).toEqual([]);
  if (!keyboard) return;
  const controls = page.locator('main :is(a[href], button, input, textarea, select, summary):visible:not(:disabled)');
  await page.locator("main").focus();
  // Polling pages and late secondary resources (Household's contacts) change the control list
  // mid-sweep, so each Tab resolves the controls, the expected next one and the focused element
  // in one page call instead of trusting an index snapshot taken before the sweep.
  // ponytail: a DOM change landing between the key press and that call can still misalign one step.
  let previous = await page.evaluateHandle(() => document.activeElement!);
  for (;;) {
    await page.keyboard.press("Tab");
    const step = await controls.evaluateAll((els, previous) => {
      const expected = els.find(el => previous.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
      const active = document.activeElement;
      const name = (el: Element | null | undefined) => el ? `${el.tagName} ${el.textContent?.trim().slice(0, 40)}` : "none";
      return expected && {
        expected: name(expected), focused: active === expected, active: name(active),
        outline: parseFloat(getComputedStyle(expected).outlineWidth),
      };
    }, previous);
    if (!step) break;
    expect(step.focused, `Tab reached ${step.active}, expected ${step.expected}`).toBe(true);
    expect(step.outline, step.expected).toBeGreaterThan(0);
    previous = await page.evaluateHandle(() => document.activeElement!);
  }
}
