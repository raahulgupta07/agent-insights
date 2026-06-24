from typing import Optional, List, Any
from pydantic import BaseModel, Field


class RunSkillFileInput(BaseModel):
    """Input schema for the ``run_skill_file`` tool.

    Executes a bundled L3 *script* (kind='script') from a loaded skill by the
    skill's exact name plus a relative path under ``scripts/``. The script must
    define ``generate_df(ds_clients, excel_files, *args, **kwargs)`` and return a
    pandas DataFrame. It runs in the same AST-gated sandbox as widget code:
    forbidden imports (os/sys/subprocess/...) and SQL writes are rejected before
    execution. Data is reached through the ``ds_clients`` passed in — already
    scoped to the calling user's credentials — never via the filesystem.
    """

    skill: str = Field(
        ...,
        description="The exact skill name from the SKILLS catalog.",
    )
    path: str = Field(
        ...,
        description='Relative path of the script within the skill bundle, e.g. "scripts/cohort.py".',
    )
    args: Optional[str] = Field(
        default=None,
        description="Optional positional argument string forwarded to generate_df.",
    )
    sql: Optional[str] = Field(
        default=None,
        description=(
            "SQL to run; its rows are passed to the skill as input_df. Use for "
            "joins/aggregations. Prefer returning columns named `item` and `value`."
        ),
    )
    data_source: Optional[str] = Field(
        default=None,
        description="data source / client key to run sql against; default = first/only.",
    )
    title: Optional[str] = Field(
        default=None,
        description=(
            "Short, SPECIFIC title for the result this run produces, e.g. "
            "'Artist Revenue Pareto' or 'Customers by Country'. ALWAYS set a "
            "distinct title when you run the same skill more than once in a turn "
            "— it labels the chart/step so you (and the user) can tell the runs "
            "apart and reuse them in create_artifact. Without it every run is "
            "indistinguishable."
        ),
    )


class RunSkillFileOutput(BaseModel):
    success: bool
    skill: Optional[str] = None
    path: Optional[str] = None
    rows: Optional[int] = None
    columns: Optional[List[str]] = None
    preview: Optional[List[Any]] = None
    stdout: Optional[str] = None
    message: Optional[str] = None
