import threading
import socket
import atexit
from rich import print
from rich.console import Console
import random
import json
from datetime import datetime
import logging
import time
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer # Re-adding Buffer for explicit type hinting if needed, though not strictly used in current logic
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
import asyncio
import sys # Import sys for sys.exit()
from pyngrok import ngrok


# Configure logging
logging.basicConfig(filename="starchat-debug.log", level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DEBUG_MODE = False

def debug(msg):
    if DEBUG_MODE:
        logging.debug(f"[DEBUG] {msg}")
        print(f"[cyan][DEBUG {datetime.now().strftime('%H:%M:%S')}][/cyan] {msg}")

port = 7001
screenName = None
auth = None
console = Console()
version = "1.0.0-Launchpad"
clients = []  # list of tuples (conn, screenName)
clients_lock = threading.Lock()

app = None  # prompt_toolkit Application instance
chat_output = None  # TextArea for chat output
input_field = None  # TextArea for user input
conn_socket = None  # For client socket
is_server = False

# --- prompt_toolkit UI setup ---

def setup_ui():
    global chat_output, input_field, app, header

    chat_output = TextArea(style="class:output-field", scrollbar=True, wrap_lines=True, focusable=False)
    input_field = TextArea(height=1, prompt='> ', style="class:input-field")

    # Top bar with auth and screen name
    header = TextArea(
        "Connected Using Client 😊",
        style="class:header",
        height=1,
        focusable=False
    )

    kb = KeyBindings()

    @kb.add('enter')
    def _(event):
        user_text = input_field.text.strip()
        if not user_text:
            return

        # Clear the input field immediately
        input_field.text = ''

        # --- Handle Exit Command ---
        if user_text.lower() == '/exit':
            add_message("[System] Initiating shutdown...")
            if is_server:
                shutdown_server()
            else:
                shutdown_client()
            return # Prevent further processing of the "exit" command
        # --- End Exit Command Handling ---

        timestamp = datetime.now().strftime('%H:%M:%S %Y-%m-%d')
        full_msg = f"[{timestamp}] [{screenName}]: {user_text}"

        if is_server:
            add_message(full_msg)
            broadcast(full_msg, sender_conn=None) # Server broadcasts its own message
        else:
            add_message(full_msg) # Client adds its own message to its display
            try:
                if conn_socket:
                    conn_socket.sendall(user_text.encode())
                else:
                    add_message("[Error] Not connected to a server.")
            except Exception as e:
                add_message(f"[Error] Failed to send message: {e}")
                debug(f"Client send error: {e}")


    root_container = HSplit([
        header,
        Frame(chat_output, title='StarChat'),
        Frame(input_field, title='ChatBox'),
    ])

    layout = Layout(root_container, focused_element=input_field)

    style = Style.from_dict({
        'output-field': 'bg:#657d6e #ffffff',
        'input-field': 'bg:#000000 #ffffff',
        'frame.label': 'bg:#03A062 #ffffff',
        'header': 'fg:#000000 bg:#444444 bold'
    })

    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)

def add_message(msg: str):
    # Thread-safe addition of message to output pane
    if app and chat_output and app.loop: # Ensure app.loop is available
        asyncio.run_coroutine_threadsafe(_append_message(msg), app.loop)
    else:
        # Fallback for messages before UI is fully set up (e.g., initial system messages)
        print(msg)

async def _append_message(msg: str):
    chat_output.buffer.insert_text(msg + '\n')
    chat_output.buffer.cursor_down(count=1000)  # Scroll to bottom

# --- Network & Chat logic ---

def broadcast(message, sender_conn):
    with clients_lock:
        to_remove = []
        for conn, client_name in clients:
            if conn != sender_conn:
                try:
                    debug(f"Broadcasting to {client_name}: {message}")
                    conn.sendall(message.encode())
                except Exception as e:
                    debug(f"Error broadcasting to {client_name}: {e}")
                    to_remove.append((conn, client_name))
        for item in to_remove:
            clients.remove(item)
            add_message(f"[System] {item[1]} disconnected due to error during broadcast.")

def handle_client(conn, addr):
    clientScreenName = "Unknown" # Initialize for finally block
    try:
        conn.sendall(b"Mayday")
        data = conn.recv(1024).decode()
        infoPack = json.loads(data)
        tempauth = int(infoPack[0])
        clientScreenName = infoPack[1]

        if tempauth != auth:
            conn.sendall(b"[X] Auth Failed.")
            conn.close()
            add_message(f"[System] Connection rejected from {addr}, invalid auth.")
            debug(f"Auth failed for {addr}. Expected: {auth}, Received: {tempauth}")
            return

        with clients_lock:
            clients.append((conn, clientScreenName))
            debug(f"Client {clientScreenName} ({addr}) connected. Current clients: {len(clients)}")


        welcome_info = json.dumps({
            "message": f"[System] Welcome to {screenName}'s Server, {clientScreenName}!",
            "hostScreenName": screenName,
            "clientScreenName": clientScreenName
        })
        conn.sendall(welcome_info.encode())
        add_message(f"[System] {clientScreenName} connected from {addr}")
        broadcast(f"[System] {clientScreenName} has joined the chat.", sender_conn=conn)

        while True:
            msg = conn.recv(1024).decode()
            if not msg or msg == "[DISCONNECT]":
                break
            timestamp = datetime.now().strftime('%H:%M:%S %Y-%m-%d')
            full_msg = f"[{timestamp}] [{clientScreenName}]: {msg}"
            add_message(full_msg)
            broadcast(full_msg, sender_conn=conn)
    except Exception as e:
        add_message(f"[Error] Connection with client {clientScreenName} ({addr}) lost: {e}")
        debug(f"Error in handle_client for {clientScreenName} ({addr}): {e}")
    finally:
        with clients_lock:
            clients[:] = [(c, n) for c, n in clients if c != conn]
            debug(f"Client {clientScreenName} ({addr}) removed. Remaining clients: {len(clients)}")

        conn.close()
        add_message(f"[System] {clientScreenName} disconnected.")
        # Only broadcast if it's not during a server shutdown (to avoid race conditions)
        # This part assumes normal client disconnect, not server initiated shutdown
        broadcast(f"[System] {clientScreenName} has left the chat.", sender_conn=None)

# Global flag to signal server shutdown
server_shutdown_event = threading.Event()

def start_server(host, port):
    global is_server
    is_server = True
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((host, port))
        server_socket.listen()
        print(f"[System] Server attempting to start on {host}:{port}")
        debug(f"Server listening on {host}:{port}")

        # Start the prompt_toolkit application in a separate thread.
        threading.Thread(target=app.run, daemon=True).start()
        time.sleep(0.5) # Give the UI a bit more time to fully initialize its loop

    except Exception as e:
        print(f"[X] Failed to start server: {e}")
        debug(f"Failed to bind server socket: {e}")
        return

    def accept_loop():
        add_message(f"[System] Server successfully started and listening on {host}:{port}")
        while not server_shutdown_event.is_set(): # Check shutdown flag
            try:
                server_socket.settimeout(1.0) # Set a timeout to allow checking the shutdown flag
                conn, addr = server_socket.accept()
                server_socket.settimeout(None) # Reset timeout
                debug(f"Accepted connection from {addr}")
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                # Timeout occurred, check shutdown flag again
                continue
            except OSError as e:
                if server_shutdown_event.is_set():
                    debug(f"Server accept loop exiting due to shutdown: {e}")
                else:
                    debug(f"Server accept loop error: {e}")
                break
            except Exception as e:
                debug(f"Unexpected error in server accept loop: {e}")
                break
        debug("Server accept loop finished.")
        server_socket.close() # Close the server socket when the loop ends

    # Now start the server's accept loop in a separate thread
    threading.Thread(target=accept_loop, daemon=True).start()

def shutdown_server():
    debug("Initiating server shutdown process.")
    add_message("[System] Server is shutting down...")
    broadcast("[System] Server is shutting down. Disconnecting...", sender_conn=None) # Inform clients

    # Signal the accept loop to stop
    server_shutdown_event.set()

    # Close all client connections
    with clients_lock:
        for conn, client_name in clients:
            try:
                conn.sendall(b"[DISCONNECT]")
                conn.close()
                add_message(f"[System] Disconnected client {client_name}.")
            except Exception as e:
                debug(f"Error closing connection to {client_name}: {e}")
        clients.clear() # Clear the list

    # Exit the prompt_toolkit application
    if app:
        app.exit()
    debug("Server shutdown complete.")
    # Consider sys.exit() if app.exit() doesn't terminate the program
    # sys.exit(0) # This will force exit, use with caution if other cleanup is needed

def start_client(host, port):
    global conn_socket, is_server
    is_server = False
    conn_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        print(f"[System] Attempting to connect to {host}:{port}...")
        conn_socket.connect((host, port))
        debug(f"Successfully connected to {host}:{port}")

        # Start the prompt_toolkit application in a separate thread.
        threading.Thread(target=app.run, daemon=True).start()
        time.sleep(0.5) # Give the UI a bit more time to fully initialize its loop and app.loop

    except Exception as e:
        print(f"[X] Could not connect to server: {e}")
        debug(f"Failed to connect to server {host}:{port}: {e}")
        return

    try:
        greeting = conn_socket.recv(1024).decode()
        if greeting != "Mayday":
            print("[X] Server did not send expected greeting. Disconnecting.")
            debug(f"Unexpected server greeting: {greeting}")
            conn_socket.close()
            return

        auth_info = json.dumps([auth, screenName])
        conn_socket.sendall(auth_info.encode())
        response = conn_socket.recv(1024).decode()

        try:
            welcome_data = json.loads(response)
            add_message(welcome_data['message'])
            debug(f"Received welcome message: {welcome_data['message']}")
        except json.JSONDecodeError:
            print(f"[X] Failed to parse welcome message from server: {response}")
            conn_socket.close()
            return
        except Exception as e:
            print(f"[X] Error processing welcome message: {e}")
            debug(f"Error processing welcome message: {e}")
            conn_socket.close()
            return

        threading.Thread(target=client_receive_loop, args=(conn_socket,), daemon=True).start()

    except Exception as e:
        print(f"[Error] Initial client setup failed: {e}")
        debug(f"Initial client setup error: {e}")
        if conn_socket:
            conn_socket.close()

def client_receive_loop(conn):
    try:
        while True:
            msg = conn.recv(1024).decode()
            if not msg or msg == "[DISCONNECT]":
                add_message("[System] Disconnected from server.")
                break
            add_message(msg)
            debug(f"Client received: {msg}")
    except OSError as e:
        add_message(f"[System] Connection to server lost: {e}")
        debug(f"Client socket error: {e}")
    except Exception as e:
        add_message(f"[Error] Unexpected error in client receive loop: {e}")
        debug(f"Client receive loop general error: {e}")
    finally:
        if conn:
            conn.close()
        # If client receive loop ends, it means we're disconnected, so shut down the client app
        if app and not is_server: # Only auto-exit if it's a client
            app.exit()

def shutdown_client():
    debug("Initiating client shutdown process.")
    add_message("[System] Disconnecting from server...")
    try:
        if conn_socket:
            conn_socket.sendall(b"[DISCONNECT]")
            conn_socket.close()
    except Exception as e:
        debug(f"Error sending disconnect message or closing client socket: {e}")
    finally:
        if app:
            app.exit()
    debug("Client shutdown complete.")
    # sys.exit(0) # This will force exit, use with caution if other cleanup is needed

# --- Your original helper functions (like prepInit) ---

def introScreen(version_str, screen_name_str, auth_code_str):
    print("""
.▄▄ · ▄▄▄▄▄ ▄▄▄· ▄▄▄   ▄▄·  ▄ .▄ ▄▄▄· ▄▄▄▄▄
▐█ ▀. •██  ▐█ ▀█ ▀▄ █·▐█ ▌▪██▪▐█▐█ ▀█ •██
▄▀▀▀█▄ ▐█.▪▄█▀▀█ ▐▀▀▄ ██ ▄▄██▀▐█▄█▀▀█  ▐█.▪
▐█▄▪▐█ ▐█▌·▐█ ▪▐▌▐█•█▌▐███▌██▌▐▀▐█ ▪▐▌ ▐█▌·
 ▀▀▀▀  ▀▀▀  ▀  ▀ .▀  ▀·▀▀▀ ▀▀▀ · ▀  ▀  ▀▀▀
""")
    print(f"""
============---------
Version[{version_str}] - Screen Name [{screen_name_str}] - Auth Code [{auth_code_str}]
============---------
""")

def prepInit(current_auth, current_screen_name, current_version):
    if current_auth is None:
        current_auth = random.randint(1000, 9999)
        debug(f"Generated random auth code: {current_auth}")

    if current_screen_name is None or current_screen_name.strip() == "":
        while True:
            name_input = input("# Setup [ScreenName]: ").strip()
            if name_input:
                current_screen_name = name_input
                debug(f"User input screenName: {current_screen_name}")
                break
            else:
                print("[X] Screen Name cannot be empty. Please try again.")

    introScreen(current_version, current_screen_name, current_auth)
    return current_auth, current_screen_name

# --- Main entrypoint ---

def main():
    global auth, screenName, header_text

    auth, screenName = prepInit(auth, screenName, version)
    debug(f"Initialized with screenName={screenName}, auth={auth}")

    setup_ui() # Call setup_ui before prompting for choice

    print(f"""
//////////////////////
NetHandler P2P Edition -=- {version}

===== Hosting =====
1. Host - Server for Connection from client
2. Client - Connecting to Host from client

""")

    choice = input("# Net [Hosting]: ").strip()

    if choice == '1':
        mode = input("# Net [Mode] - Choose Mode [1] LAN or [2] Public: ").strip()

        if mode == "1":
            host_ip = "0.0.0.0" # Listen on all available interfaces
            port_input = input("# Net [Host Port] - Pick a Local Port to Listen |Default=7001|: ").strip()
            port_to_use = int(port_input) if port_input.isdigit() else port # Validate port input
            if not (1024 <= port_to_use <= 65535):
                print("[X] Port must be between 1024 and 65535.")
                return
            
            header.text = f"🌐 Connected via LAN | Auth Code: {auth} | {screenName} | Public IP: {host_ip}:{port_to_use}"
            
            start_server(host_ip, port_to_use)

            try:
                while app.is_running: # Keep main thread alive as long as app is running
                    time.sleep(1)
            except KeyboardInterrupt:
                add_message("[System] Server shutting down (Ctrl+C detected)...")
                shutdown_server() # Call shutdown function on Ctrl+C
            except Exception as e:
                debug(f"Main thread unexpected error: {e}")
            finally:
                if app.is_running: # If app is still running for some reason, ensure exit
                    app.exit()
                debug("Main thread exiting for server.")


        elif mode == "2":
            print("[System] Starting ngrok tunnel...")

            # Start ngrok tunnel
            try:
                public_tunnel = ngrok.connect(port, "tcp")  # 'tcp' because you're using raw sockets
                public_url = public_tunnel.public_url  # e.g., tcp://0.tcp.ngrok.io:12345
                host_port = public_url.split("tcp://")[1]
                host, public_port = host_port.split(":")
                public_port = int(public_port)

                print(f"[✔] Public ngrok tunnel established!")
                print(f"[INFO] Share this IP with clients: {host}")
                print(f"[INFO] Share this Port with clients: {public_port}")
                print(f"[INFO] Auth Code: {auth}")
                print(f"[INFO] Screen Name: {screenName}")
                debug(f"ngrok public URL: {public_url}")
                
                header.text = f"🌐 Connected via ngrok | Auth Code: {auth} | {screenName} | Public IP: {public_url}:{public_port}"
                
                start_server("0.0.0.0", port)  # Bind locally, ngrok forwards traffic here

                while app.is_running:
                    time.sleep(1)

            except Exception as e:
                print(f"[X] Failed to start ngrok tunnel: {e}")
                debug(f"ngrok error: {e}")


    elif choice == '2':
        host = input("# Net [Host IP] - Insert Host IP: ").strip()
        while not host:
            print("[X] Host IP cannot be empty.")
            host = input("# Net [Host IP] - Insert Host IP: ").strip()

        try:
            port_to_use = int(input("# Net [Host Port]: ").strip())
            if not (1024 <= port_to_use <= 65535):
                print("[X] Port must be between 1024 and 65535.")
                return
            hostauth = int(input("# Net [Host Auth]: ").strip())
        except ValueError:
            print("[X] Port and Auth must be numbers.")
            return

        auth = hostauth # Client uses the host's auth code

        start_client(host, port_to_use)

        try:
            while app.is_running: # Keep main thread alive as long as app is running
                time.sleep(1)
        except KeyboardInterrupt:
            add_message("[System] Client shutting down (Ctrl+C detected)...")
            shutdown_client() # Call shutdown function on Ctrl+C
        except Exception as e:
            debug(f"Main thread unexpected error: {e}")
        finally:
            if app.is_running: # If app is still running for some reason, ensure exit
                app.exit()
            debug("Main thread exiting for client.")

    else:
        print("[X] Invalid choice.")

if __name__ == "__main__":
    atexit.register(ngrok.kill)
    main()