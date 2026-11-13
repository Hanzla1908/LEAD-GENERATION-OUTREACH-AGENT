'use strict'

const http = require('node:http')
const crypto = require('node:crypto')

const MAX_BODY_BYTES = 64 * 1024
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
const PLACEHOLDER_DOMAINS = new Set([
  'example.com', 'example.org', 'example.net', 'test.com', 'domain.com', 'email.com', 'localhost',
])
const ALLOWED_FIELDS = new Set(['idempotency_key', 'to', 'subject', 'text', 'unsubscribe_url'])
const HTTP_URL_PATTERN = /^https?:\/\/[^\s<>]+$/

function isValidRecipient(address) {
  if (typeof address !== 'string' || !EMAIL_PATTERN.test(address)) return false
  return !PLACEHOLDER_DOMAINS.has(address.split('@')[1].toLowerCase())
}

function validateSendRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return 'Body must be a JSON object.'
  for (const field of Object.keys(body)) {
    if (!ALLOWED_FIELDS.has(field)) {
      return `Unexpected field "${field}". Each message has exactly one recipient and no copies.`
    }
  }
  if (typeof body.idempotency_key !== 'string' || body.idempotency_key.length < 8 || body.idempotency_key.length > 200) {
    return 'idempotency_key must be 8 to 200 characters.'
  }
  if (!isValidRecipient(body.to)) return 'to must be one valid business email address.'
  if (typeof body.subject !== 'string' || !body.subject.trim() || body.subject.length > 200 || /[\r\n]/.test(body.subject)) {
    return 'subject must be 1 to 200 characters on a single line.'
  }
  if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > 20000) {
    return 'text must be 1 to 20000 characters.'
  }
  if (body.unsubscribe_url !== undefined && (typeof body.unsubscribe_url !== 'string' || !HTTP_URL_PATTERN.test(body.unsubscribe_url))) {
    return 'unsubscribe_url must be an http or https URL.'
  }
  return null
}

function classifyFailure(err) {
  if (err && err.code === 'EENVELOPE') return 'not_sent'
  if (err && (err.command === 'MAIL FROM' || err.command === 'RCPT TO')) return 'not_sent'
  if (err && err.code === 'ECONNECTION' && (!err.command || err.command === 'CONN')) return 'not_sent'
  return 'unknown'
}

function secretsMatch(provided, expected) {
  const a = Buffer.from(typeof provided === 'string' ? provided : '')
  const b = Buffer.from(expected)
  return a.length === b.length && crypto.timingSafeEqual(a, b)
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > MAX_BODY_BYTES) {
        reject(Object.assign(new Error('Request body is too large.'), { status: 413 }))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null'))
      } catch {
        reject(Object.assign(new Error('Request body is not valid JSON.'), { status: 400 }))
      }
    })
    req.on('error', reject)
  })
}

function createApp({ secret, mailer, ledger, from, mode }) {
  if (!secret || secret.length < 16) throw new Error('secret must be at least 16 characters')

  return http.createServer(async (req, res) => {
    const reply = (status, body) => {
      res.writeHead(status, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(body))
    }

    try {
      // Public liveness probe for the hosting platform. It reveals nothing about configuration.
      if (req.method === 'GET' && req.url === '/livez') {
        return reply(200, { status: 'ok' })
      }
      if (!secretsMatch(req.headers['x-service-secret'], secret)) {
        return reply(401, { error: 'Unauthorized' })
      }
      if (req.method === 'GET' && req.url === '/health') {
        return reply(200, { status: 'ok', mode })
      }
      if (req.method === 'POST' && req.url === '/send') {
        return await handleSend(req, reply)
      }
      return reply(404, { error: 'Not found' })
    } catch (err) {
      if (err.status) return reply(err.status, { error: err.message })
      return reply(500, { error: 'Internal error' })
    }
  })

  async function handleSend(req, reply) {
    const body = await readJson(req)
    const problem = validateSendRequest(body)
    if (problem) return reply(400, { error: problem })

    const key = body.idempotency_key
    const previous = ledger.get(key)
    if (previous) {
      if (previous.status === 'sent') {
        return reply(200, { message_id: previous.message_id, duplicate: true })
      }
      return reply(409, {
        error: 'An earlier attempt with this key has an unknown outcome. It was not resent.',
        outcome: 'unknown',
      })
    }

    ledger.reserve(key)
    const message = { from, to: body.to, subject: body.subject, text: body.text, headers: {} }
    if (body.unsubscribe_url) {
      message.headers['List-Unsubscribe'] = `<${body.unsubscribe_url}>`
      message.headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
    }

    try {
      const info = await mailer.sendMail(message)
      ledger.markSent(key, info.messageId)
      return reply(200, { message_id: info.messageId, duplicate: false })
    } catch (err) {
      if (classifyFailure(err) === 'not_sent') {
        ledger.release(key)
        return reply(422, { error: String(err.message).slice(0, 300), outcome: 'not_sent' })
      }
      ledger.markUnknown(key, err.message)
      return reply(502, {
        error: 'Delivery outcome is unknown. Check the provider before retrying.',
        outcome: 'unknown',
      })
    }
  }
}

module.exports = { createApp, validateSendRequest, classifyFailure, isValidRecipient }
