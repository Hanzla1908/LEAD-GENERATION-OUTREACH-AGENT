'use strict'

const { loadConfig } = require('./config')
const { createMailer } = require('./mailer')
const { SendLedger } = require('./ledger')
const { createApp } = require('./app')

let config
try {
  config = loadConfig()
} catch (err) {
  console.error(`Email service configuration error: ${err.message}`)
  process.exit(1)
}

const server = createApp({
  secret: config.secret,
  mailer: createMailer(config),
  ledger: new SendLedger(config.ledgerPath),
  from: config.from,
  mode: config.mode,
})

server.listen(config.port, config.host, () => {
  console.log(`Email service listening on http://${config.host}:${config.port} (mode: ${config.mode})`)
})
