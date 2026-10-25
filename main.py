""" uv init my_project
cd my_project
uv add requests     # creates .venv automatically (if missing) and installs requests
uv run main.py      # runs your script using the project's .venv
""" 

def main():
    print("Hello from lab1!")


if __name__ == "__main__":
    main()
