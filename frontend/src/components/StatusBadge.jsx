export default function StatusBadge({ status }) {
  const styles = {
    ok: { background: '#d1fae5', color: '#065f46' },
    error: { background: '#fee2e2', color: '#991b1b' },
    checking: { background: '#fef3c7', color: '#92400e' },
  }
  const s = styles[status] ?? styles.checking
  return (
    <span style={{ ...s, padding: '2px 10px', borderRadius: 12, fontSize: 13, fontWeight: 600 }}>
      {status}
    </span>
  )
}
