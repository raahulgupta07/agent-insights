from app.project_manager import ProjectManager
import os
import re
from app.models.data_source import DataSource
from app.ai.llm import LLM
import pandas as pd
import json
from app.models.llm_model import LLMModel
from app.dependencies import async_session_maker

"""
"""


def _clean_ds_name(raw: str | None) -> str:
    """Strip connector auth-method framing from a data-source display name so it
    can't poison LLM domain inference.

    The per-user connector names a source after HOW we connect, not WHAT the data
    is — e.g. "Power BI (User Sign-in) · tester3@test.com". A weak model reads
    "User Sign-in" and invents a whole authentication-log schema (@SignInLogs …)
    that does not exist. Neutralise it to just the platform ("Power BI").
    """
    n = (raw or "datasource").split("·")[0]                       # drop " · email"
    n = re.sub(r"\(\s*(user\s*)?sign[\s-]?in\s*\)", "", n, flags=re.I)  # drop "(User Sign-in)"
    n = re.sub(r"\s+", " ", n).strip(" -–—")
    return n or "datasource"


def _table_allowlist(schema: str) -> list[str]:
    """Best-effort extract the real table names present in a rendered schema string.

    Supports both the XML render (`<table name="...">`) and the plain
    TableFormatter render (`Table: Foo` / bare `Foo/Bar` dataset-qualified names).
    Used to hard-forbid the LLM inventing tables not in the schema.
    """
    names: list[str] = []
    names += re.findall(r'<table[^>]*\bname="([^"]+)"', schema)
    # plain-text fallback (TableFormatter): "Dataset Name/Table" or "Table:" lines
    names += re.findall(r'(?im)^\s*(?:table:\s*)?([A-Za-z0-9_][A-Za-z0-9_ ]*/[A-Za-z0-9_ #]+?)\s*(?:\(|:|$)', schema)
    # dedup preserve order
    seen, out = set(), []
    for x in names:
        x = x.strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:80]


def _example_values_block(schema: str) -> str:
    """Best-effort compact "example values" block from the rendered schema.

    The learn-from-data sampler writes real sampled values to
    ``DataSourceTable.columns[].metadata['values']`` and the schema renderer
    surfaces them as a ``values="a, b, c"`` attribute on each ``<column .../>``.
    Pull up to ~4 values for a handful of low-cardinality/categorical columns so
    conversation starters can name concrete segments/periods. Fail-soft: any
    error (or no values present) → returns "" and the caller keeps the
    schema-only prompt byte-identical.
    """
    try:
        def _unescape(s: str) -> str:
            return (
                s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                 .replace("&quot;", '"').replace("&#39;", "'")
            )

        lines: list[str] = []
        for m in re.finditer(r'<column\b([^>]*?)/?>', schema or ""):
            if len(lines) >= 8:
                break
            attrs = m.group(1)
            nm = re.search(r'\bname="([^"]*)"', attrs)
            vals = re.search(r'\bvalues="([^"]*)"', attrs)
            if not nm or not vals:
                continue
            # Skip obviously numeric columns — their values aren't "segments".
            dt = re.search(r'\bdtype="([^"]*)"', attrs)
            dtype = (dt.group(1).lower() if dt else "")
            if any(k in dtype for k in ("int", "float", "double", "decimal", "numeric", "number")):
                continue
            name = _unescape(nm.group(1)).strip()
            raw = _unescape(vals.group(1))
            parts = [p.strip() for p in raw.split(",") if p.strip() and not p.strip().startswith("…")]
            parts = parts[:4]
            if name and parts:
                lines.append(f"- {name}: {', '.join(parts)}")
        if not lines:
            return ""
        return (
            "\nExample real values from the data (reference these concrete "
            "segments/periods in the starters where relevant):\n"
            + "\n".join(lines)
            + "\n"
        )
    except Exception:
        return ""


def _grounding_block(clean_name: str, schema: str) -> str:
    """Hard grounding preamble prepended to every onboarding generator prompt."""
    tables = _table_allowlist(schema)
    tbl_line = (", ".join(tables)) if tables else "(see schema below)"
    return f"""CRITICAL GROUNDING RULES — read before writing anything:
- The connector/agent name ("{clean_name}") describes the PLATFORM and how we connect (login method). It does NOT tell you what the data is about. Do NOT infer the business domain from the name.
- Infer the domain ONLY from the actual table names, column names, and any example values in the schema below.
- You may reference ONLY these tables that actually exist: {tbl_line}. NEVER invent a table, column, or concept that is not in the schema (e.g. do not write about "sign-in logs", "authentication attempts", "@SignInLogs" unless such a table literally appears above).
- If the schema does not contain data for a concept, do not describe that concept at all.

"""


class DataSourceAgent:

    def __init__(self, data_source: DataSource, schema: str, model: LLMModel):
        self.data_source = data_source
        self.llm = LLM(model, usage_session_maker=async_session_maker)
        self.schema = schema
        self.clean_name = _clean_ds_name(getattr(data_source, "name", None))
        self.grounding = _grounding_block(self.clean_name, schema or "")

    def generate_summary(self):
        prompt = f"""{self.grounding}
Data source name: {self.clean_name}

Schema:
{self.schema}

Write exactly 1 sentence   describing this data source. First: what it is. Second: what key data it contains.

Rules:
- No fluff, no "this data source contains", no markdown, no bullet points.
- Plain text only.
- Max 30 words total.
"""
        response = self.llm.inference(prompt, usage_scope="data_source.summary")
        return response

    def generate_conversation_starters(self):
        # STARTERS_DATA_GROUNDED (flag-gated): also surface real sampled values so
        # starters can name concrete segments/periods. OFF or no values → "" →
        # prompt is byte-identical to the schema-only version.
        example_values = ""
        try:
            from app.settings.hybrid_flags import flags as _sg_flags
            if getattr(_sg_flags, "STARTERS_DATA_GROUNDED", False):
                example_values = _example_values_block(self.schema or "")
        except Exception:
            example_values = ""

        prompt = f"""{self.grounding}
Given this data source:
{self.clean_name}

And this schema
{self.schema}
{example_values}
Please generate 4 conversation starters grounded in the ACTUAL tables and columns above (never about concepts not present in the schema). Return them in a strict JSON array format.

The response should be an array of strings, where each string contains a title and detailed prompt separated by a newline character.

A few examples:
- Title: Top Customers
  Prompt: List the top 10 customers by revenue. Measure revenue by summing the total payments. Show name, email,  geo, total revenue, and total payments
- Title: Best Sellers
  Prompt: List the top 10 products by revenue. Measure revenue by summing the total payments. Show name, total revenue, and total payments
- Title: Unhappy Customers
  Prompt: List the top 10 customers by negative reviews. Show name, email, geo, total reviews, and total negative reviews
- Title: Customers Churn Root Cause
  Prompt: List the top 10 customers by churn. Show name, email, geo, total churn, and total churn reason.
- Title: Stray Cloud Users
  Prompt: List the top 10 users who are not in the cloud. Show name, email, geo, total users, and total users not in the cloud.

Example format:
[
    "Starter 1 Title\\nStarter 1 detailed prompt",
    "Starter 2 Title\\nStarter 2 detailed prompt",
    "Starter 3 Title\\nStarter 3 detailed prompt",
    "Starter 4 Title\\nStarter 4 detailed prompt"
]

Important: in the output, do not include "Title" or "Prompt" in the output. just the list of conversation starters. Separete between Title and Prompt with a newline character.
Important: Return only the JSON array with no additional text, formatting, or explanations. Ensure all newlines are properly escaped with \\n.
Do not add prefix ``` or markdown or anything. just the list of conversation starters.
"""

        response = self.llm.inference(prompt, usage_scope="data_source.conversation_starters")
        # Strip any potential whitespace or extra characters
        response = response.strip()
        json_response = json.loads(response)
        list_response = list(json_response)

        return list_response
    

    def generate_context(self):
        pass

    def generate_datasource_instruction(self) -> dict:
        """Generate a single comprehensive overview instruction for this data source.

        Returns a dict with keys: title, text, category, load_mode, confidence.
        Title follows the pattern {DS_NAME}_OVERVIEW.
        """
        ds_name = self.clean_name or "datasource"
        title = ds_name.upper().replace(" ", "_").replace("-", "_") + "_OVERVIEW"

        prompt = f"""You are a data analyst onboarding a new data source for an AI analytics agent.

{self.grounding}
Data source/Agent name: {ds_name}

Schema:
{self.schema}

Your task: write a single comprehensive instruction that the AI analytics agent will load every time it works with this data source. This instruction is its permanent reference card.

The instruction must cover:
- What this data source represents and its business purpose
- Key tables and what each tracks (1 line per table, focused on business meaning)
- Important relationships between tables (joins, foreign keys worth knowing)
- Any naming conventions, column quirks, or non-obvious facts visible in the schema (e.g. status codes, units, soft deletes)
- Primary identifiers and date/time columns to use for filtering

Rules:
- Be specific and factual — ground every claim in the schema, never invent
- No fluff, no generic statements like "this data source contains data about..."
- Write as direct instructions to the AI analyst ("Use X to...", "Always join on...", "Note that...")
- Plain prose with short bullet points where helpful
- 150–300 words
- When referencing a table from the schema, write its name as @TableName (e.g. @orders, @customers)
- When referencing an MCP tool from the schema, write its name as @tool_name (e.g. @search_products)

Return JSON only:
{{"title": "{title}", "text": "...", "category": "general", "load_mode": "always", "confidence": 0.95}}"""

        response = self.llm.inference(prompt, usage_scope="data_source.instruction")
        response = response.strip()
        # Strip markdown code fences if present
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        try:
            return json.loads(response.strip())
        except Exception:
            return {
                "title": title,
                "text": response.strip(),
                "category": "general",
                "load_mode": "always",
                "confidence": 0.9,
            }


    def generate_description(self):
        prompt = f"""{self.grounding}
Given this data source:
{self.clean_name}

And this schema
{self.schema}

Please review the schema (tables, columns, example values). Then, understand the nature of the data source FROM THE SCHEMA ONLY, think about the purpose of the data source, and generate a description for the data source. Make it useful for a non-technical audience.
Description should be max 3 sentences. Should be concise, valuable, and useful.

Guidelines:
- Make it personalized based on the data schema. 
- Don't make it generic.
- Don't make it too long. Max 3 sentences. No more than 280 characters.
- Don't use fluff words. Be direct and to the point.
- Be factual when describing the data source.
- Use simple language, make it extremely to point, not fluff, and be very brief and concise.
- Don't say "This data source contains information about...". Just describe the data source.

Examples:
- "Salesforce CRM data that provides information about customers, opportunities, leads, and marketing campaigns."
- "Google Analytics data that provides information about website traffic, user behavior, and marketing effectiveness."
- "Jira data that provides information about engineering projects, tasks, and team performance."
"""
        response = self.llm.inference(prompt, usage_scope="data_source.description")
        return response