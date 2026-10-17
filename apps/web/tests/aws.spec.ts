import { test, expect } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';

const folder = process.env.HIRZ_AWS_ARTIFACTS;
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

test('AWS HTTPS enrollment, activation, login and authenticated reads', async ({ page, context }) => {
  test.skip(!folder, 'Requires explicit item 36 AWS acceptance artifacts');
  const invitation = JSON.parse(await readFile(`${folder}/invite.json`, 'utf8'));
  expect(invitation.origin).toMatch(/^https:\/\/[a-z0-9]+\.cloudfront\.net$/);
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', { options: { protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  await page.goto(invitation.origin);
  await page.getByText('Set up a passkey or recover access').click();
  await page.getByLabel('Invitation or one-time recovery code').fill(invitation.token);
  await page.getByRole('button', { name: 'Enroll a passkey' }).click();
  await expect(page.getByRole('heading', { name: 'Save this code now' })).toBeVisible();
  const recovery = await page.locator('code').textContent();
  await writeFile(`${folder}/recovery.txt`, recovery!, { mode: 0o600, flag: 'wx' });
  await page.getByRole('button', { name: 'I saved my recovery code' }).click();
  await page.getByRole('link', { name: 'Constitution', exact: true }).click();
  await page.getByRole('button', { name: 'Preview changes' }).click();
  await page.getByRole('button', { name: 'Activate with passkey' }).click();
  await expect(page.getByRole('heading', { name: /Version 7 · active/ })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  const read = await page.evaluate(async () => {
    const response = await fetch('/api/household');
    return { status: response.status, data: await response.json() };
  });
  expect(read.status).toBe(200);
  await writeFile(`${folder}/browser.json`, JSON.stringify({ status: 'passed', origin: invitation.origin, virtual_authenticator: true, real_passkey: 'pending', read_status: read.status }), { mode: 0o600, flag: 'wx' });
});
