'use strict'

const { test, before, after, beforeEach } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { createApp, validateSendRequest, classifyFailure } = require('../src/app')
const { SendLedger } = require('../src/ledger')
const { createMailer } = require('../src/mailer')
const { loadConfig } = require('../src/config')

const SECRET = 'test-secret-value-1234'

function makeFakeMailer() {
  const mailer = {
    sent: [],
    nextError: null,
    async sendMail(message) {
      if (mailer.nextError) {
        const error = mailer.nextError
        mailer.nextError = null
        throw error
      }
      mailer.sent.push(message)
      return { messageId: `<msg-${mailer.sent.length}@test>` }
    },
  }
  return mailer
}

function validBody(overrides = {}) {
  return {
    idempotency_key: 'campaign-1-recipient-1',
    to: 'owner@karahicorner.pk',
    subject: 'Idea for Karahi Corner',
    text: 'Hello Karahi Corner team.',
    unsubscribe_url: 'https://outreach.example.pk/unsubscribe?r=1&t=abc',
    ...overrides,
  }
}

let tempDir
let server
let baseUrl
let mailer
let ledger

before(() => {
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'email-service-test-'))
})

after(async () => {
  if (server) {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
  }
  fs.rmSync(tempDir, { recursive: true, force: true })
})

beforeEach(async () => {
  if (server) {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
  }
  mailer = makeFakeMailer()
  ledger = new SendLedger(path.join(tempDir, `ledger-${Date.now()}-${Math.random()}.json`))
  server = createApp({ secret: SECRET, mailer, ledger, from: 'Outreach <outreach@example.org>', mode: 'mock' })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  baseUrl = `http://127.0.0.1:${server.address().port}`
})

async function call(method, route, { body, secret = SECRET } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (secret !== null) headers['X-Service-Secret'] = secret
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return { status: response.status, json: await response.json() }
}

test('every route requires the internal service secret', async () => {
  const missing = await call('POST', '/send', { body: validBody(), secret: null })
  const wrong = await call('POST', '/send', { body: validBody(), secret: 'wrong-secret-value-9999' })
  assert.equal(missing.status, 401)
  assert.equal(wrong.status, 401)
  assert.equal((await call('GET', '/health', { secret: null })).status, 401)
  assert.equal(mailer.sent.length, 0)
})

test('health reports the mode when the secret is correct', async () => {
  const health = await call('GET', '/health')
  assert.equal(health.status, 200)
  assert.deepEqual(health.json, { status: 'ok', mode: 'mock' })
})

test('liveness is public and reveals nothing about the configuration', async () => {
  const live = await call('GET', '/livez', { secret: null })
  assert.equal(live.status, 200)
  assert.deepEqual(live.json, { status: 'ok' })
})

test('a valid message is sent once with the list-unsubscribe headers', async () => {
  const result = await call('POST', '/send', { body: validBody() })
  assert.equal(result.status, 200)
  assert.equal(result.json.duplicate, false)
  assert.equal(mailer.sent.length, 1)
  const [message] = mailer.sent
  assert.equal(message.to, 'owner@karahicorner.pk')
  assert.equal(message.cc, undefined)
  assert.equal(message.bcc, undefined)
  assert.equal(message.headers['List-Unsubscribe'], '<https://outreach.example.pk/unsubscribe?r=1&t=abc>')
  assert.equal(message.headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
})

test('repeating the same idempotency key never sends a second message', async () => {
  const first = await call('POST', '/send', { body: validBody() })
  const second = await call('POST', '/send', { body: validBody() })
  assert.equal(first.json.message_id, second.json.message_id)
  assert.equal(second.json.duplicate, true)
  assert.equal(mailer.sent.length, 1)
})

test('a key left pending by a crash blocks resending', async () => {
  ledger.reserve('campaign-1-recipient-9')
  const result = await call('POST', '/send', { body: validBody({ idempotency_key: 'campaign-1-recipient-9' }) })
  assert.equal(result.status, 409)
  assert.equal(result.json.outcome, 'unknown')
  assert.equal(mailer.sent.length, 0)
})

test('copies, extra fields and multiple recipients are rejected', async () => {
  for (const field of ['cc', 'bcc', 'to_list']) {
    const result = await call('POST', '/send', { body: validBody({ [field]: 'extra@karahicorner.pk' }) })
    assert.equal(result.status, 400, field)
  }
  assert.equal(mailer.sent.length, 0)
})

test('placeholder and malformed recipients are rejected', async () => {
  for (const to of ['owner@example.com', 'not-an-email', 'owner@cafe', '', 'a@b.pk, c@d.pk']) {
    const result = await call('POST', '/send', { body: validBody({ to, idempotency_key: `key-${to}-12345` }) })
    assert.equal(result.status, 400, to)
  }
  assert.equal(mailer.sent.length, 0)
})

test('subjects with line breaks are rejected to block header injection', async () => {
  const result = await call('POST', '/send', { body: validBody({ subject: 'Hi\r\nBcc: victim@x.pk' }) })
  assert.equal(result.status, 400)
  assert.equal(mailer.sent.length, 0)
})

test('unsubscribe links must be http or https', async () => {
  const result = await call('POST', '/send', { body: validBody({ unsubscribe_url: 'javascript:alert(1)' }) })
  assert.equal(result.status, 400)
})

test('a refused recipient is reported as not sent and can be retried', async () => {
  const refused = Object.assign(new Error('Recipient refused'), { code: 'EENVELOPE', command: 'RCPT TO' })
  mailer.nextError = refused
  const failed = await call('POST', '/send', { body: validBody() })
  assert.equal(failed.status, 422)
  assert.equal(failed.json.outcome, 'not_sent')

  const retried = await call('POST', '/send', { body: validBody() })
  assert.equal(retried.status, 200)
  assert.equal(mailer.sent.length, 1)
})

test('a connection lost during delivery is reported unknown and never resent', async () => {
  mailer.nextError = Object.assign(new Error('Connection dropped'), { code: 'ECONNRESET', command: 'DATA' })
  const failed = await call('POST', '/send', { body: validBody() })
  assert.equal(failed.status, 502)
  assert.equal(failed.json.outcome, 'unknown')

  const retried = await call('POST', '/send', { body: validBody() })
  assert.equal(retried.status, 409)
  assert.equal(mailer.sent.length, 0)
})

test('unknown routes return 404', async () => {
  assert.equal((await call('GET', '/nope')).status, 404)
})

test('validateSendRequest accepts the documented shape only', () => {
  assert.equal(validateSendRequest(validBody()), null)
  assert.match(validateSendRequest(null), /JSON object/)
  assert.match(validateSendRequest(validBody({ idempotency_key: 'short' })), /idempotency_key/)
})

test('classifyFailure separates refusals from unknown outcomes', () => {
  assert.equal(classifyFailure({ code: 'EENVELOPE' }), 'not_sent')
  assert.equal(classifyFailure({ command: 'MAIL FROM' }), 'not_sent')
  assert.equal(classifyFailure({ code: 'ECONNECTION', command: 'CONN' }), 'not_sent')
  assert.equal(classifyFailure({ command: 'DATA' }), 'unknown')
  assert.equal(classifyFailure(new Error('boom')), 'unknown')
})

test('the send ledger survives a restart and still blocks duplicates', async () => {
  const file = path.join(tempDir, 'restart-ledger.json')
  const first = new SendLedger(file)
  first.markSent('campaign-7-recipient-3', '<persisted@test>')
  const reopened = new SendLedger(file)
  assert.equal(reopened.get('campaign-7-recipient-3').message_id, '<persisted@test>')
})

test('config refuses unknown modes, short secrets and SMTP without a host', () => {
  assert.throws(() => loadConfig({ MAIL_MODE: 'carrier-pigeon', EMAIL_SERVICE_SECRET: SECRET }), /MAIL_MODE/)
  assert.throws(() => loadConfig({ EMAIL_SERVICE_SECRET: 'short' }), /at least 16/)
  assert.throws(() => loadConfig({ MAIL_MODE: 'smtp', MAIL_FROM: 'a@b.org', EMAIL_SERVICE_SECRET: SECRET }), /SMTP_HOST/)
})

test('mock mode is the default and needs no SMTP settings', async () => {
  const config = loadConfig({ EMAIL_SERVICE_SECRET: SECRET })
  assert.equal(config.mode, 'mock')
  const mock = createMailer(config)
  const info = await mock.sendMail({ from: 'a@b.org', to: 'c@d.pk', subject: 'x', text: 'y' })
  assert.ok(info.messageId)
})
