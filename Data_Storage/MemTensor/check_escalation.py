def check_escalation(mem_tensor):
    # Columns to watch for conflicts (indices in your MemTensor)
    # 2: Hunger, 4: Mating, 5: Threat, 6: Critical_Health
    interaction_columns = [2, 4, 5, 6]
    
    # 1. Sum up the active states across these columns for every agent
    # .sum(dim=1) gives us a 1D tensor of scores [0, 1, 2, 0, 3...]
    conflict_scores = mem_tensor[:, interaction_columns].sum(dim=1)
    
    # 2. If score >= 2, flip the Intent_Flag (Column 7)
    mem_tensor[conflict_scores >= 2, 7] = 1
    
    # 3. If score < 2 and they were thinking, we can optionally clear it 
    # (though usually, we let the LLM finish its thought first)
    # mem_tensor[conflict_scores < 2, 7] = 0