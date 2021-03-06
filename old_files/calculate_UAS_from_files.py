import os
import numpy as np

folder = '../code_directory/data'
ground_truth = 'test.labeled'
original_train = os.path.join(folder,ground_truth)
predicted = '../code_directory/tagged_test_file_m2.labeled'


# change to the relevant size #
num_sentences = 1000

def get_all_heads_from_file(file):
    sentence_num = 0
    sentence_heads = []
    heads = np.zeros((num_sentences, 1), dtype='object')

    with open(file, 'r') as file_reader:
        for i, line in enumerate(file_reader):
            if line.strip():
                split_words = line.split('\t')
                curr_head = split_words[6]
                sentence_heads.append(curr_head)
            else:
                heads[sentence_num,0] = np.array(sentence_heads)
                sentence_num += 1
                sentence_heads = []
    file_reader.close()
    return heads

def calc_uas(GT,predicted):
    uas_total = 0
    total_num_words = 0
    correct_sum = 0
    gt_train_heads = get_all_heads_from_file(GT)
    pred_train_heads = get_all_heads_from_file(predicted)
    for i in range(num_sentences):
        num_correct = np.sum(gt_train_heads[i, 0] == pred_train_heads[i, 0])
        correct_sum += num_correct
        curr_sentence = gt_train_heads[i,0]
        num_words_in_sentence = gt_train_heads[i, 0].shape[0]
        total_num_words += num_words_in_sentence
        curr_uas = num_correct / num_words_in_sentence
        uas_total += curr_uas
    average_uas_sentences = uas_total / num_sentences
    average_uas_words = correct_sum / total_num_words
    print(average_uas_sentences, average_uas_words)


calc_uas(original_train,predicted)
print("")

