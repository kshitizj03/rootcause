export function Method() {
  return (
    <section className="method wrap" id="method">
      <span className="eyebrow">Method</span>
      <h2 className="big">Hard to fool.</h2>
      <div className="cols">
        <div>
          <h3>Recorded, not simulated</h3>
          <p>Every fault was injected into the running OpenTelemetry Demo and captured: metrics, traces and logs, with the true cause stored apart.</p>
        </div>
        <div>
          <h3>Leak-proofed</h3>
          <p>Flag names, delay markers and alert wording that could give the cause away are stripped, and a scan checks every recording.</p>
        </div>
        <div>
          <h3>Rules fixed first</h3>
          <p>Scoring was written before the first run. Four no-fault controls punish false alarms. One author: every threat to validity is listed.</p>
        </div>
      </div>
    </section>
  )
}
