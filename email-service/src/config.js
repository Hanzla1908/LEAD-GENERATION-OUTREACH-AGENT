'use strict'

const path = require('node:path')

const MIN_SECRET_LENGTH = 16

function loadConfig(env = process.env) {
  const mode = (env.MAIL_MODE || 'mock').trim().toLowerCase()
  if (mode !== 'mock' && mode !== 'smtp') {
    throw new Error('MAIL_MODE must be "mock" or "smtp".')
  }

  const secret = env.EMAIL_SERVICE_SECRET || ''
  if (secret.length < MIN_SECRET_LENGTH) {
    throw new Error(`EMAIL_SERVICE_SECRET must be at least ${MIN_SECRET_LENGTH} characters.`)
  }

  const from = (env.MAIL_FROM || 'Outreach <outreach@example.org>').trim()
  const smtp = {
    host: (env.SMTP_HOST || '').trim(),
    port: Number(env.SMTP_PORT || 587),
    secure: env.SMTP_SECURE === 'true',
    user: env.SMTP_USER || '',
    pass: env.SMTP_PASS || '',
  }
  if (mode === 'smtp') {
    if (!smtp.host) throw new Error('MAIL_MODE=smtp requires SMTP_HOST.')
    if (!env.MAIL_FROM) throw new Error('MAIL_MODE=smtp requires MAIL_FROM.')
  }

  return {
    mode,
    secret,
    from,
    smtp,
    host: env.EMAIL_SERVICE_HOST || '127.0.0.1',
    port: Number(env.EMAIL_SERVICE_PORT || 3001),
    ledgerPath: env.SEND_LEDGER_PATH || path.join(__dirname, '..', 'data', 'send-ledger.json'),
  }
}

module.exports = { loadConfig, MIN_SECRET_LENGTH }
