"""
Adaptive Abstraction and Key-phrase (AAK) Compression for Sigil.
Reduces token count when injecting memories into LLM context.
Target: >20% compression while maintaining semantic fidelity.
"""

import re
from typing import Optional


class AAKCompressor:
    """
    Compresses memory content for injection into LLM context windows.
    Three strategies: dedup, abstraction, key-phrase extraction.
    """

    # Common filler patterns to strip
    FILLER_PATTERNS = [
        r'\b(basically|essentially|actually|literally|obviously|clearly)\b',
        r'\b(in order to)\b',
        r'\b(at this point in time)\b',
        r'\b(due to the fact that)\b',
        r'\b(it is important to note that)\b',
        r'\b(as a matter of fact)\b',
        r'\b(in terms of)\b',
        r'\b(with regard to)\b',
        r'\b(at the end of the day)\b',
        r'\b(for all intents and purposes)\b',
    ]

    # Replacements for verbose phrases
    VERBOSE_TO_CONCISE = {
        "in order to": "to",
        "due to the fact that": "because",
        "at this point in time": "now",
        "with regard to": "regarding",
        "in the event that": "if",
        "for the purpose of": "to",
        "in the process of": "while",
        "on a daily basis": "daily",
        "at the present time": "now",
        "in the near future": "soon",
        "prior to": "before",
        "subsequent to": "after",
        "in addition to": "besides",
        "a large number of": "many",
        "a small number of": "few",
        "the majority of": "most",
        "is able to": "can",
        "is unable to": "cannot",
        "make a decision": "decide",
        "take into consideration": "consider",
        "come to the conclusion": "conclude",
        "give consideration to": "consider",
        "have the ability to": "can",
    }

    def __init__(self, target_reduction: float = 0.20):
        self.target_reduction = target_reduction

    def compress(self, text: str) -> str:
        """Apply all compression strategies."""
        result = text

        # Strategy 1: Verbose phrase replacement
        result = self._replace_verbose(result)

        # Strategy 2: Remove filler words
        result = self._remove_filler(result)

        # Strategy 3: Collapse whitespace
        result = self._collapse_whitespace(result)

        # Strategy 4: Deduplicate sentences
        result = self._dedup_sentences(result)

        return result.strip()

    def compress_memories(self, memories: list[dict],
                          max_tokens: int = 2000) -> str:
        """
        Compress a list of memory results for injection.
        Returns a formatted, compressed context block.
        """
        lines = []
        total_chars = 0
        char_limit = max_tokens * 4  # Rough chars per token

        # Sort by score/importance
        sorted_mems = sorted(memories,
                             key=lambda m: m.get("score", m.get("importance", 0.5)),
                             reverse=True)

        for mem in sorted_mems:
            content = mem.get("content", "")
            compressed = self.compress(content)

            # Prefix with type indicator
            table = mem.get("table", "")
            prefix = {"semantic": "F", "episodic": "E",
                      "procedural": "P", "working": "W"}.get(table, "*")

            line = f"[{prefix}] {compressed}"
            line_len = len(line)

            if total_chars + line_len > char_limit:
                # Truncate to fit
                remaining = char_limit - total_chars - len(f"[{prefix}] ")
                if remaining > 20:
                    lines.append(f"[{prefix}] {compressed[:remaining]}...")
                break

            lines.append(line)
            total_chars += line_len

        return "\n".join(lines)

    def _replace_verbose(self, text: str) -> str:
        """Replace verbose phrases with concise alternatives."""
        result = text
        for verbose, concise in self.VERBOSE_TO_CONCISE.items():
            result = re.sub(re.escape(verbose), concise, result, flags=re.IGNORECASE)
        return result

    def _remove_filler(self, text: str) -> str:
        """Remove filler words."""
        result = text
        for pattern in self.FILLER_PATTERNS:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        return result

    def _collapse_whitespace(self, text: str) -> str:
        """Collapse multiple spaces/newlines."""
        result = re.sub(r'\s+', ' ', text)
        result = re.sub(r'\n\s*\n', '\n', result)
        return result

    def _dedup_sentences(self, text: str) -> str:
        """Remove duplicate or near-duplicate sentences."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        seen = set()
        unique = []

        for s in sentences:
            # Normalize for comparison
            normalized = re.sub(r'\s+', ' ', s.lower().strip())
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(s)

        return " ".join(unique)

    def stats(self, original: str, compressed: str) -> dict:
        """Compression statistics."""
        orig_tokens = len(original) / 4
        comp_tokens = len(compressed) / 4
        reduction = 1 - (comp_tokens / max(1, orig_tokens))

        return {
            "original_chars": len(original),
            "compressed_chars": len(compressed),
            "original_tokens_est": int(orig_tokens),
            "compressed_tokens_est": int(comp_tokens),
            "reduction_pct": round(reduction * 100, 1),
            "target_met": reduction >= self.target_reduction,
        }
