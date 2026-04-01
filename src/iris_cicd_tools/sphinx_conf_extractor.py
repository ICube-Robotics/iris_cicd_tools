import json
import runpy
import sys
from typeguard import typechecked
import click

@typechecked
@click.command()
@click.option('--config-path', default='source/conf.py', help='Path to the Sphinx conf.py file', type=click.Path(exists=True, dir_okay=False))
def get_html_context(config_path: str) -> str:
    try:
        # run_path executes the python file safely in its own namespace
        namespace = runpy.run_path(config_path)
        
        # Extract the variable (default to empty dict if not found)
        html_context = namespace.get('html_context', {})
        
        # Print it to stdout so Dagger/Invoke can capture it. 
        # We use default=str to prevent crashes if the dict contains non-serializable objects (like functions)
        print(json.dumps(html_context, default=str))
        
    except Exception as e:
        print(f"Error parsing conf.py: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    get_html_context()