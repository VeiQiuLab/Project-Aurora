use std::collections::HashMap;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestOwner {
    pub request_id: String,
    pub session_id: String,
    pub generation_id: String,
}

#[derive(Clone, Debug)]
struct RequestEntry {
    owner: RequestOwner,
    expected_seq: u64,
    accepted: bool,
    cancel_requested: bool,
    terminal_state: Option<String>,
}

#[derive(Debug, Default)]
pub struct RequestRegistry {
    entries: HashMap<(String, String), RequestEntry>,
}

impl RequestRegistry {
    pub fn start(&mut self, owner: RequestOwner) -> Result<(), String> {
        if self
            .entries
            .values()
            .any(|entry| entry.terminal_state.is_none())
        {
            return Err("another generation is still active".into());
        }
        let key = (owner.session_id.clone(), owner.generation_id.clone());
        if self.entries.contains_key(&key) {
            return Err("generation_id cannot be reused".into());
        }
        self.entries.insert(
            key,
            RequestEntry {
                owner,
                expected_seq: 0,
                accepted: false,
                cancel_requested: false,
                terminal_state: None,
            },
        );
        Ok(())
    }

    pub fn accept(&mut self, owner: &RequestOwner) -> Result<(), String> {
        let entry = self.entry_mut(owner)?;
        if entry.accepted || entry.terminal_state.is_some() {
            return Err("duplicate or stale chat.accepted".into());
        }
        entry.accepted = true;
        Ok(())
    }

    pub fn delta(&mut self, owner: &RequestOwner, seq: u64) -> Result<(), String> {
        let entry = self.entry_mut(owner)?;
        if !entry.accepted || entry.terminal_state.is_some() {
            return Err("delta does not belong to an active accepted generation".into());
        }
        if seq != entry.expected_seq {
            return Err(format!("invalid seq: expected {}", entry.expected_seq));
        }
        entry.expected_seq += 1;
        Ok(())
    }

    pub fn request_cancel(&mut self, owner: &RequestOwner) -> Result<bool, String> {
        let entry = self.entry_mut(owner)?;
        if entry.terminal_state.is_some() {
            return Ok(false);
        }
        entry.cancel_requested = true;
        Ok(true)
    }

    pub fn terminal(&mut self, owner: &RequestOwner, state: &str) -> Result<bool, String> {
        let entry = self.entry_mut(owner)?;
        if entry.terminal_state.is_some() {
            return Ok(false);
        }
        entry.terminal_state = Some(state.to_owned());
        Ok(true)
    }

    pub fn backend_lost(&mut self) -> Vec<RequestOwner> {
        let mut lost = Vec::new();
        for entry in self.entries.values_mut() {
            if entry.terminal_state.is_none() {
                entry.terminal_state = Some("backend_lost".into());
                lost.push(entry.owner.clone());
            }
        }
        lost
    }

    #[cfg(test)]
    pub fn is_cancel_requested(&self, owner: &RequestOwner) -> bool {
        self.entries
            .get(&(owner.session_id.clone(), owner.generation_id.clone()))
            .is_some_and(|entry| entry.cancel_requested)
    }

    fn entry_mut(&mut self, owner: &RequestOwner) -> Result<&mut RequestEntry, String> {
        let entry = self
            .entries
            .get_mut(&(owner.session_id.clone(), owner.generation_id.clone()))
            .ok_or_else(|| "stale or unknown generation".to_string())?;
        if entry.owner.request_id != owner.request_id {
            return Err("request_id does not own generation".into());
        }
        Ok(entry)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn owner(generation: &str) -> RequestOwner {
        RequestOwner {
            request_id: format!("request-{generation}"),
            session_id: "session-1".into(),
            generation_id: generation.into(),
        }
    }

    #[test]
    fn ordered_sequence_and_single_terminal_are_enforced() {
        let mut registry = RequestRegistry::default();
        let owner = owner("one");
        registry.start(owner.clone()).unwrap();
        registry.accept(&owner).unwrap();
        registry.delta(&owner, 0).unwrap();
        registry.delta(&owner, 1).unwrap();
        assert!(registry.delta(&owner, 1).is_err());
        assert!(registry.terminal(&owner, "completed").unwrap());
        assert!(!registry.terminal(&owner, "cancelled").unwrap());
        assert!(registry.delta(&owner, 2).is_err());
    }

    #[test]
    fn cancel_is_idempotent_and_does_not_override_terminal() {
        let mut registry = RequestRegistry::default();
        let owner = owner("cancel");
        registry.start(owner.clone()).unwrap();
        assert!(registry.request_cancel(&owner).unwrap());
        assert!(registry.request_cancel(&owner).unwrap());
        assert!(registry.is_cancel_requested(&owner));
        assert!(registry.terminal(&owner, "cancelled").unwrap());
        assert!(!registry.request_cancel(&owner).unwrap());
    }

    #[test]
    fn backend_lost_only_terminalizes_active_generations() {
        let mut registry = RequestRegistry::default();
        let first = owner("first");
        registry.start(first.clone()).unwrap();
        registry.terminal(&first, "completed").unwrap();
        let second = owner("second");
        registry.start(second.clone()).unwrap();
        assert_eq!(registry.backend_lost(), vec![second.clone()]);
        assert!(!registry.terminal(&second, "completed").unwrap());
    }

    #[test]
    fn old_request_identity_cannot_mutate_new_generation() {
        let mut registry = RequestRegistry::default();
        let current = owner("current");
        registry.start(current.clone()).unwrap();
        let mut wrong = current.clone();
        wrong.request_id = "old-request".into();
        assert!(registry.accept(&wrong).is_err());
        registry.accept(&current).unwrap();
    }
}
