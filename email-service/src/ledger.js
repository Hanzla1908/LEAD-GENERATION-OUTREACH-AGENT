'use strict'

const fs = require('node:fs')
const path = require('node:path')

class SendLedger {
  constructor(filePath) {
    this.filePath = filePath
    this.entries = {}
    if (fs.existsSync(filePath)) {
      const raw = fs.readFileSync(filePath, 'utf8')
      this.entries = raw.trim() ? JSON.parse(raw) : {}
    }
  }

  get(key) {
    return this.entries[key] || null
  }

  reserve(key) {
    if (this.entries[key]) throw new Error('Idempotency key already reserved.')
    this.entries[key] = { status: 'pending', updated_at: new Date().toISOString() }
    this.save()
  }

  markSent(key, messageId) {
    this.entries[key] = { status: 'sent', message_id: messageId, updated_at: new Date().toISOString() }
    this.save()
  }

  markUnknown(key, detail) {
    this.entries[key] = { status: 'unknown', detail: String(detail).slice(0, 300), updated_at: new Date().toISOString() }
    this.save()
  }

  release(key) {
    delete this.entries[key]
    this.save()
  }

  save() {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
    const temporary = `${this.filePath}.tmp`
    fs.writeFileSync(temporary, JSON.stringify(this.entries, null, 2))
    fs.renameSync(temporary, this.filePath)
  }
}

module.exports = { SendLedger }
