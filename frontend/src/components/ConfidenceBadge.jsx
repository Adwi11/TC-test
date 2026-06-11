export default function ConfidenceBadge({ conf }) {
  if (!conf || typeof conf.score !== 'number') return null;
  const score = conf.score;
  const tier = score >= 0.85 ? 'high' : score >= 0.6 ? 'med' : 'low';
  const label = `${Math.round(score * 100)}%`;
  const showSource = conf.source === 'regex';
  const tail = showSource ? ` · ${conf.source}` : '';
  return <span className={`badge ${tier}`} title={`${label}${tail}`}>{label}{tail}</span>;
}
