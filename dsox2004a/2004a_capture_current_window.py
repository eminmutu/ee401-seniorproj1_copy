import pyvisa
import time

rm = pyvisa.ResourceManager()
# Replace with your actual VISA address
scope_address = 'USB0::0x0957::0x179A::MY52141103::INSTR' 
scope = rm.open_resource(scope_address)

scope.timeout = 10000 
scope.chunk_size = 20480

try:
    print("Requesting screen capture...")
    
    # CHANGED: datatype='B' (Unsigned char) instead of 'b'
    image_data = scope.query_binary_values(
        ':DISPlay:DATA? PNG, COLor', 
        datatype='B', 
        is_big_endian=False, 
        container=bytearray
    )

    filename = f"scope_screen_{int(time.time())}.png"
    with open(filename, 'wb') as f:
        f.write(image_data)
    
    print(f"Success! Screen captured to {filename}")

except Exception as e:
    print(f"Error: {e}")

finally:
    scope.close()