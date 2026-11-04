// For browser tests about what comes after the consent and age step (docs/specs/consent-and-age.md): answer it through
// the screen as an adult who ticks every point, whichever part of it this browser still has to answer. Nothing to answer
// is fine: a context answers it once and the later takes go straight to the recorder.
export async function answerConsentStep(page) {
  const visible = (id) => page.locator(`[data-testid="${id}"]:visible`).first();
  const seen = ["countdown-select", "age-month", "consent-agree"].map((id) => `[data-testid="${id}"]:visible`).join(", ");
  await page.locator(seen).first().waitFor();
  if (await visible("age-month").count()) {
    await visible("age-month").selectOption("1");
    await visible("age-year").selectOption("1990");
    await visible("age-next").click();
    await visible("consent-agree").waitFor();
  }
  if (await visible("consent-agree").count()) {
    for (const box of await page.locator('[data-testid^="consent-item-"]:visible').all()) await box.check();
    await visible("consent-agree").click();
  }
  await visible("countdown-select").waitFor();
}
