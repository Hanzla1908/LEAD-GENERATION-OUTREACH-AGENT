import { useEffect, useState } from 'react'
import { getRestaurantConversations } from '../services/api'
import { Modal } from './ui'
import { DELIVERY_LABEL } from './DeliveryPanel'

const MATCH_TEXT = {
  matched: 'Linked to a campaign email',
  needs_review: 'Uncertain match, waiting for review',
}

// Message text is rendered as plain text by React. Nothing from a message is written as HTML.
export default function ConversationHistory({ restaurant, onClose }) {
  const [state, setState] = useState({ loading: false, error: '', data: null })

  useEffect(() => {
    if (!restaurant) return undefined
    let active = true
    setState({ loading: true, error: '', data: null })
    getRestaurantConversations(restaurant.id)
      .then((data) => { if (active) setState({ loading: false, error: '', data }) })
      .catch((err) => { if (active) setState({ loading: false, error: err.message || 'Could not load history.', data: null }) })
    return () => { active = false }
  }, [restaurant])

  const events = state.data?.events ?? []
  const replies = state.data?.replies ?? []

  return (
    <Modal
      open={Boolean(restaurant)}
      title={`History: ${restaurant?.name ?? ''}`}
      description="Confirmed delivery events and replies, shown as plain text."
      onClose={onClose}
      size="md"
    >
      {state.loading && <p className="muted">Loading…</p>}
      {state.error && <div className="notice notice-bad" role="alert">{state.error}</div>}
      {!state.loading && !state.error && state.data && events.length === 0 && replies.length === 0 && (
        <p className="muted">No confirmed delivery events or replies for this business yet.</p>
      )}

      {events.length > 0 && (
        <>
          <h3>Delivery events</h3>
          <ul className="history-list">
            {events.map((event) => (
              <li key={event.id}>
                <strong>{DELIVERY_LABEL[event.event_type] ?? event.event_type}</strong>
                <span className="muted small"> · {event.source === 'webhook' ? 'provider webhook' : 'bounce message'} · {event.received_at}</span>
                {event.reason && <div className="small">{event.reason}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {replies.length > 0 && (
        <>
          <h3>Replies</h3>
          <ul className="history-list">
            {replies.map((reply) => (
              <li key={reply.id}>
                <strong>{reply.subject || '(no subject)'}</strong>
                <span className="muted small"> · {reply.from_address || 'unknown sender'} · {reply.received_at}</span>
                <div className="small muted">{MATCH_TEXT[reply.match_status] ?? reply.match_status}</div>
                <p className="reply-text">{reply.body_text || '(no text content)'}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  )
}
