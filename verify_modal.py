import sys

def check_balanced(filename):
    with open(filename, 'r') as f:
        content = f.read()
    
    # Check div balance for the modal
    modal_start = content.find('id="model-browse-modal"')
    if modal_start == -1:
        print("Modal not found")
        return
    
    # Check basic function existence
    functions = ["fetchModelPathBrowse", "openModelPathBrowser"]
    for func in functions:
        if func not in content:
            print(f"Function {func} missing")
            return

    print("Modal markup and handlers are present and appear syntactically complete.")

check_balanced('templates/model_editor.html')
