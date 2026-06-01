import mido

port_name = mido.get_input_names()[0]
print("Listening on:", port_name)

with mido.open_input(port_name) as port:
    for msg in port:
        print(msg)