import matplotlib.pyplot as plt

def probability_successful_transmission(p, N):
    return p * (1 - p)**(N - 1)

p = 0.2  # Probability for a node to transmit in a slot
N_values = range(1, 21)  # Number of nodes ranging from 1 to 20

probabilities = [probability_successful_transmission(p, N) for N in N_values]

plt.plot(N_values, probabilities, marker='o')
plt.title('Successful Transmission dependent of num. Nodes')
plt.xlabel('Nodes')
plt.ylabel('Probability of Successful Transmission')
plt.grid(True)
plt.show()

