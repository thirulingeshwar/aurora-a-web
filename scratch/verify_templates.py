import os
import jinja2

def verify_templates():
    templates_dir = 'templates'
    loader = jinja2.FileSystemLoader(templates_dir)
    env = jinja2.Environment(loader=loader)
    
    success = True
    for filename in os.listdir(templates_dir):
        if filename.endswith('.html'):
            try:
                env.get_template(filename)
                print(f"[OK] {filename} compiles successfully!")
            except Exception as e:
                print(f"[ERROR] {filename} failed to compile: {e}")
                success = False
    return success

if __name__ == '__main__':
    verify_templates()
