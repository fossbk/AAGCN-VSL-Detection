# AAGCN-Modified AGCN for Vietnamese Sign Language (VSL) Recognition
# Introduction
This research focuses on improving the classification accuracy of Vietnamese Sign Language (VSL) through a modified deep learning model. The methodology involves extracting skeletal keypoints from video data via Mediapipe. A bilinear interpolation method is then applied during preprocessing to estimate and fill potentially missing keypoint data. The core model utilizes Adaptive Graph Convolutional Networks (AGCNs) combined with spatial, temporal, and channel attention mechanisms to capture relevant sign features effectively. Evaluation was conducted on a novel VSL dataset, collected specifically for this study at a school for deaf and hard-of-hearing children in Hanoi, Vietnam. This dataset contains 5,572 videos from 28 participants, encompassing 199 distinct sign classes representative of frequently used Vietnamese vocabulary. Prior to training on this VSL data, transfer learning was employed: the model was pre-trained on the Ankara University Turkish Sign Language (AUTSL) dataset to initialize weights, facilitating subsequent fine-tuning on our VSL dataset.

# Setup
Download all the files and run the jupyter file total_vsl. This file will do almost the entire training process, ranging from extracting the keypoints to performing interpolation, training the model. All the other files are the supplement for the model part. 

Change the path of the input dataset. The code will read all videos in the folder.

In file total_vsl, there are 2 options:
1. Train new.
2. Train continuously from the model that was trained on the AUTSL dataset.

Uncomment the part of the code that you want to use.

# Evaluation
We use k-fold in this project with k is defined as 10. The 10 trained models will be stored in the "checkpoints" folder. The final output will print out the best accuracy.

# Acknowledgement
This project is built by iBME lab at Hanoi University of Science and Technology, Vietnam. It is funded by Hanoi University of Science and Technology (HUST) under project number T2023-PC-028.
