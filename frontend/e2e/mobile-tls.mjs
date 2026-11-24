// Run from any directory after installing the locked Python/npm dependencies and building the UI.
import { spawn, execFileSync } from 'node:child_process'
import { createHash, X509Certificate } from 'node:crypto'
import { once } from 'node:events'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import https from 'node:https'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { chromium, devices, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))

async function listen(server, host) {
  server.listen(0, host)
  await once(server, 'listening')
  return server.address().port
}

async function waitForEndpoint(origin, ca, child) {
  const deadline = Date.now() + 15000
  for (;;) {
    try {
      await new Promise((resolve, reject) => {
        const request = https.get(origin + '/api/capabilities', {ca, agent: false}, response => {
          response.resume()
          if (response.statusCode === 200) resolve()
          else reject(Error('Unexpected readiness response: ' + response.statusCode))
        })
        request.setTimeout(1500, () => request.destroy(Error('TLS readiness timeout')))
        request.once('error', reject)
      })
      return
    } catch (error) {
      if (child.exitCode !== null || child.signalCode || Date.now() >= deadline) throw error
      await delay(100)
    }
  }
}

async function check(mode) {
  const host = mode === 'lan' ? process.env.R0_TEST_LAN_IP || '127.0.0.1' : '127.0.0.1'
  const temp = await mkdtemp(path.join(os.tmpdir(), 'esports-mobile-'))
  const cert = path.join(temp, 'cert.pem')
  const key = path.join(temp, 'key.pem')
  let child, browser, relay
  try {
    execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
      '-subj', '/CN=R0-mobile-test', '-addext', 'subjectAltName=IP:' + host,
      '-keyout', key, '-out', cert], {stdio: 'ignore'})
    const certificate = await readFile(cert)
    const pubkey = new X509Certificate(certificate).publicKey.export({type: 'spki', format: 'der'})
    const pin = createHash('sha256').update(pubkey).digest('base64')
    const reservation = net.createServer()
    const backendPort = await listen(reservation, host)
    let port = backendPort
    if (mode === 'remote') {
      // Forward opaque TLS records. The browser authenticates the home server end-to-end.
      relay = net.createServer(client => {
        const upstream = net.connect(backendPort, host)
        client.pipe(upstream).pipe(client)
        client.on('error', () => upstream.destroy())
        upstream.on('error', () => client.destroy())
        client.on('close', () => upstream.destroy())
        upstream.on('close', () => client.destroy())
      })
      port = await listen(relay, host)
    }
    reservation.close()
    await once(reservation, 'close')
    const origin = 'https://' + host + ':' + port
    child = spawn(process.env.PYTHON || 'python', ['-m', 'backend.run', '--mode', mode, '--host', host,
      '--port', String(backendPort), '--origin', origin, '--cert', cert, '--key', key, '--data', temp],
      {cwd: root, stdio: ['ignore', 'pipe', 'inherit'], env: {...process.env, PYTHONIOENCODING: 'utf-8'}})
    let output = ''
    child.stdout.setEncoding('utf8').on('data', part => { output += part })
    const deadline = Date.now() + 10000
    while (!output.includes('\n')) {
      if (child.exitCode !== null || Date.now() > deadline) throw Error('Server pairing code unavailable')
      await delay(50)
    }
    const code = output.trim().split(/\s+/).at(-1)
    // The CLI prints the invitation before Uvicorn opens the listening socket.
    // Verify the actual TLS endpoint (including the relay) before browser navigation.
    await waitForEndpoint(origin, certificate, child)
    browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
      args: ['--no-proxy-server', '--ignore-certificate-errors-spki-list=' + pin,
        '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']})
    const device = await browser.newContext({...devices['Pixel 7'], locale: 'ru-RU'})
    const page = await device.newPage()
    const errors = []
    page.on('pageerror', err => errors.push(err.message))
    await page.goto(mode === 'lan' ? origin + '/#pair=' + encodeURIComponent(code) : origin)
    await expect(page.getByTestId('connection')).toHaveText('Требуется код')
    await expect(page.getByRole('button', {name:'Настройки сервера'})).toHaveCount(0)
    const field = page.getByLabel('Одноразовый код с домашнего ПК')
    if (mode === 'lan') {
      await expect(field).toHaveValue(code)
      expect(new URL(page.url()).hash).toBe('')
    } else await field.fill(code)
    await page.getByLabel('Название устройства').fill('Тестовый телефон')
    await page.getByRole('button', {name: 'Подключить', exact: true}).tap()
    await expect(page.getByTestId('connection')).toHaveText('На связи')
    await expect(page.locator('canvas')).toBeVisible()
    const button = name => page.getByRole('button', {name, exact: true})
    await button('4×').tap()
    await expect(button('4×')).toHaveAttribute('aria-pressed', 'true')
    await button('Запустить').tap()
    await expect(page.getByTestId('tick')).not.toHaveText('0')
    await button('Пауза').tap()
    await button('Сохранить').tap()
    await expect(button('Загрузить')).toBeEnabled()
    await page.reload()
    await expect(page.getByTestId('connection')).toHaveText('На связи')
    await expect(button('4×')).toHaveAttribute('aria-pressed', 'true')
    expect(errors).toEqual([])
    console.log(mode + ': mobile HTTPS/WSS, pairing, simulation, save and session restoration passed')
  } finally {
    if (browser) await browser.close()
    if (child && child.exitCode === null && child.signalCode === null) {
      const stopped = once(child, 'exit')
      child.kill()
      await stopped
    }
    if (relay) relay.close()
    await rm(temp, {recursive: true, force: true})
  }
}

for (const mode of ['lan', 'remote']) await check(mode)
