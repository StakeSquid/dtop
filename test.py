#!/usr/bin/env python3
"""
Docker TUI - Test Script
-----------
Tests the Docker TUI application with all its components.
"""
import os
import sys

def test_imports():
    """Test all module imports to ensure everything is working"""
    print("Testing imports...")
    
    try:
        import utils
        print("✓ utils module")
        
        import config
        print("✓ config module")
        
        import stats
        print("✓ stats module")
        
        import container_actions
        print("✓ container_actions module")
        
        import log_view
        print("✓ log_view module")
        
        import docker_tui
        print("✓ docker_tui module")
        
        import main
        print("✓ main module")
        
        print("\nAll modules imported successfully!")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def check_files():
    """Check if all necessary files exist"""
    required_files = [
        "main.py",
        "docker_tui.py",
        "log_view.py",
        "container_actions.py",
        "utils.py",
        "config.py",
        "stats.py",
        "normalize_logs.py",
    ]
    
    print("\nChecking required files...")
    missing_files = []
    
    for filename in required_files:
        if os.path.isfile(filename):
            print(f"✓ {filename}")
        else:
            print(f"❌ {filename} (MISSING)")
            missing_files.append(filename)
    
    if missing_files:
        print(f"\nWarning: {len(missing_files)} file(s) are missing!")
        return False
    else:
        print("\nAll required files are present!")
        return True

def check_permissions():
    """Check if files have proper execution permissions"""
    executable_files = [
        "main.py",
        "normalize_logs.py"
    ]
    
    print("\nChecking executable permissions...")
    for filename in executable_files:
        if not os.path.isfile(filename):
            print(f"❌ {filename} not found")
        elif os.access(filename, os.X_OK):
            print(f"✓ {filename} is executable")
        else:
            print(f"❌ {filename} is not executable")
            try:
                os.chmod(filename, 0o755)
                print(f"  ✓ Fixed permissions for {filename}")
            except Exception as e:
                print(f"  ❌ Unable to set permissions: {e}")

def main():
    """Run tests and checks for Docker TUI"""
    print("=" * 50)
    print("Docker TUI Test Suite")
    print("=" * 50)
    
    # Check if files exist
    files_ok = check_files()
    
    # Check permissions
    check_permissions()
    
    # Test imports only if files are present
    if files_ok:
        imports_ok = test_imports()
    else:
        print("\nSkipping import tests due to missing files.")
        imports_ok = False
    
    # Final report
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    
    if files_ok and imports_ok:
        print("✅ All tests passed! The Docker TUI is ready to run.")
        print("\nTo start the application, run:")
        print("    ./main.py")
        print("\nIf you encounter any permission issues, run:")
        print("    chmod +x main.py normalize_logs.py")
        return 0
    else:
        print("❌ Some tests failed. Please fix the issues before running Docker TUI.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
