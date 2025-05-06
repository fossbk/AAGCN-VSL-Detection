# AAGCN-Modified AGCN for Vietnamese Sign Language (VSL) Recognition
# Introduction
In this project, we modify a model to better classify Vietnamese sign language (VSL). We use Mediapipe to extract keypoints. Then apply a bilinear preprocessing technique in order to reconstruct the missing keypoints. The model is built based on the Adaptive Graph Convolutional Networks by combining with Attention Mechanisms, including spatial, temporal, and channel attention.

The model is test on our self-collected VSL dataset, which was collected from the school for hearing-impaired children in Hanoi, Vietnam. The data consists of 5,572 videos of 28 actors, with 199 classes each, representing the most frequently used spoken Vietnamese. Before training on this dataset, we pre-train the model with the Ankara University Turkish Sign Language Dataset (AUTSL) first to obtain the weights, learning rate for further training.

# Setup
Download all the files and run the jupyter file Total (VSL). This file will do almost the entire training process, ranging from extracting the keypoints to performing interpolation, training the model. All the other files are the supplement for the model part. 

Change the path of the input dataset. The code will read all videos in the folder.

In file total_vsl, there are 2 options:
1. Train new.
2. Train continuously from the model that was trained on the AUTSL dataset.

Uncomment the part of the code that you want to use.

# Evaluation
We use k-fold in this project with k is defined as 10. The 10 trained models will be stored in the "checkpoints" folder. The final output will print out the best accuracy.

# Acknowledgement
This project is built by iBME lab at Hanoi University of Science and Technology, Vietnam. It is funded by Hanoi University of Science and Technology (HUST) under project number T2023-PC-028.
