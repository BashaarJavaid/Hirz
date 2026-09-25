//! Private pipe protocol for Hirz; the pinned CLI remains the reference engine.
use std::collections::HashMap;
use std::io::{self, BufRead, Write};

use dogwood_language::{
    Authorizer, Decision, LoweredPolicySet, PolicySchema, ServiceSchema, Validator, parse_trace,
};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    policy: String,
    schema: String,
    trace: Option<String>,
}

fn evaluate(
    request: Request,
    policies: &mut HashMap<(String, String), LoweredPolicySet>,
) -> Result<Value, String> {
    let key = (request.policy, request.schema);
    let Some(trace) = request.trace else {
        if !policies.contains_key(&key) {
            let schema = PolicySchema::from_cedarschema_str(&key.1).map_err(|e| e.to_string())?;
            let lowered = LoweredPolicySet::from_str(&key.0, &ServiceSchema::defaults(), &schema)
                .map_err(|e| e.to_string())?;
            if !Validator::new().validate(&lowered).validation_passed() {
                return Err("Policy validation failed".into());
            }
            policies.insert(key, lowered);
        }
        return Ok(json!({"ready": true}));
    };
    let lowered = policies.get(&key).ok_or("Policy was not prepared")?;
    let events = parse_trace(&trace).map_err(|e| e.to_string())?;
    // Clone only compiled artifacts. Never retain an Authorizer or its history.
    let mut authorizer = Authorizer::new(lowered.clone());
    let mut verdicts = Vec::new();
    for event in &events {
        if let Some(response) = authorizer.is_authorized(event) {
            verdicts.push(json!({
                "index": verdicts.len(),
                "timestamp": event.timestamp(),
                "verdict": match response.decision() {
                    Decision::Allow => "allow",
                    Decision::Deny => "deny",
                },
                "determining_rules": response.diagnostics().reason()
                    .map(|r| r.rule_index).collect::<Vec<_>>(),
                "errors": response.diagnostics().errors().collect::<Vec<_>>(),
            }));
        }
    }
    Ok(json!({"verdicts": verdicts}))
}

fn main() -> io::Result<()> {
    // Only policies explicitly prepared during this parent's lifetime are held.
    let mut policies = HashMap::new();
    let mut output = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let result = serde_json::from_str::<Request>(&line)
            .map_err(|e| e.to_string())
            .and_then(|request| evaluate(request, &mut policies));
        // Do not expose supplied policy/trace data in errors or stderr.
        let response =
            result.unwrap_or_else(|_| json!({"error": "Native boundary rejected input"}));
        serde_json::to_writer(&mut output, &response)?;
        writeln!(output)?;
        output.flush()?;
    }
    Ok(())
}
