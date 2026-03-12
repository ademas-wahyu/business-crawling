from lead_finder.gui import launch_gui


if __name__ == "__main__":
    try:
        launch_gui()
    except Exception as exc:
        print(f"ERROR: {exc}")
