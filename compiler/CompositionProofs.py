from Abstractions import *


class Proof:
    """An abstraction of a sigma protocol proof.
    Is in this file because of And/Or operations defined here.
    """

    def __and__(self, other):
        """
        Returns an AndProof from this proof and the other proof using the infix '&' operator. 
        If called again, subproofs are merged so only one AndProof remains in the end. 
        """
        if isinstance(other, AndProof):
            if isinstance(self, AndProof):
                return AndProof(*self.subproofs, *other.subproofs)
            else:
                return AndProof(self, *other.subproofs)
        elif isinstance(self, AndProof):
            return AndProof(*self.subproofs, other)
        return AndProof(self, other)

    def __or__(self, other):
        """
        :return: an OrProof from this proof and the other proof using the infix '|' operator.
        If called again, subproofs are merged so only one OrProof remains in the end. 
        """
        if isinstance(other, OrProof):
            if isinstance(self, OrProof):
                return OrProof(*self.subproofs, *other.subproofs)
            else:
                return OrProof(self, *other.subproofs)
        elif isinstance(self, OrProof):
            return OrProof(*self.subproofs, other)
        return OrProof(self, other)

    def get_prover(self, secrets_dict={}):
        """
        Returns a Prover for the current proof.
        """
        pass

    def get_verifier(self):
        """
        Returns a Verifier for the current proof.
        """
        pass

    def recompute_commitment(self, challenge, response):

        """
        Computes a pseudo-commitment (literally, the commitment you should have received 
        if the proof was correct. To compare to the actual commitment.
        :param challenge: the challenge used in the proof
        :param response: an list of responses, ordered as the list of secret names i.e with as many elements as secrets in the proof claim.
        Reoccuring secrets should yield identical responses.
        """
        pass

    def set_simulate(self):
        self.simulation = True

    def prove(self, secret_dict={}, message=""):
        """
        Generate the transcript of a non-interactive proof.
        """
        prover = self.get_prover(secret_dict)
        return prover.get_NI_proof(message)

    def verify(self, transcript, message=""):
        """
        Verify the transcript of a non-interactive proof.
        """
        verifier = self.get_verifier()
        return verifier.verify_NI(transcript, message)

    def simulate(self, challenge=None):
        """
        Generate the transcript of a simulated non-interactive proof. 
        """
        self.set_simulate()
        transcript = self.simulate_proof(challenge=challenge)
        transcript.statement = self.prehash_statement().digest()
        return transcript

    def check_statement(self, statement):
        """
        Verifies the current proof corresponds to the hash passed as a parameter.
        Returns a preshash of the current proof, e.g to be used to verify NI proofs
        """
        cur_statement = self.prehash_statement()
        if statement != cur_statement.digest():
            raise Exception("Proof statements mismatch, impossible to verify")
        return cur_statement

    
    def check_or_flaw(self, forbidden_secrets=None):
        """
        Check if a secret appears both inside an outside an Or Proof. Does nothing if not overriden.
        """
        pass

    def update_randomizers(self, randomizers_dict):
        """
        Constructs a full dictionary of randomizers (also used as responses in simulations) by copying the values of the dict passed as parameter,
        and drawing the other values at random until all the secrets have a randomizer.
        :param randomizers_dict: A dictionary to enforce 
        """
        # If we are not provided a randomizer dict from above, we compute it.
        if randomizers_dict is None:
            randomizers_dict = self.get_randomizers()
        # If we were passed an incomplete dictionary, fill it
        elif any([x not in randomizers_dict for x in self.secret_vars]):
            tmp = self.get_randomizers()
            tmp.update(randomizers_dict)
            randomizers_dict = tmp
        return randomizers_dict

    def ec_encode(self, data):
        """
        Figures out which encoder to use in the petlib.pack function encode() and uses it.
        Can break if both petlib.ec.EcPt points and custom BilinearPairings points are used in the same proof.
        """
        if not isinstance(self.generators[0], EcPt):
            encoding = enc_GXpt
        else:
            encoding = None
        return encode(data, custom_encoder=encoding)

    def prehash_statement(self, other=None):
        """
        Returns a hash of the proof's descriptor.
        Since for now proofs mixing EcPt and G1Pt are not supported, we typecheck to encode with the petlib.pack function.
        :arg other: An optional other object to pack, e.g a commitment (for non-interactive proofs). Avoids having to figure out the encoding mode multiple times.
        """
        ppp = sha256(self.ec_encode(self.get_proof_id()))
        return ppp

    def verify_simulation_consistency(self, transcript):
        """
        Tool function useful for debugging. Checks if a the fields of a transcript satisfy the verification equation.
        Should NOT be used instead of proof.verify() since it would accept simulations !
        """
        verifier = self.get_verifier()
        verifier.process_precommitment(transcript.precommitment)
        self.check_statement(transcript.statement)
        verifier.commitment, verifier.challenge = (
            transcript.commitment,
            transcript.challenge,
        )
        return verifier.verify(transcript.responses)


def find_residual_chal(arr, challenge, chal_length):
    """ 
    Tool function to determine the complement to a global challenge in a list, i.e:
    To find c1 such that c = c1 + c2 +c3 mod k,
    We compute c2 + c3 -c and take the opposite
    :param arr: The array of subchallenges c2, c3...
    :param challenge: The global challenge to reach
    :param chal_length: the modulus to reduce to
    """
    modulus = Bn(2).pow(chal_length)
    temp_arr = arr.copy()
    temp_arr.append(-challenge)
    return -add_Bn_array(temp_arr, modulus)


def sub_proof_prover(sub_proof, secrets_dict):
    """
    Tool function used in both Or and And proofs to get a prover from a subproof
    by giving it only the secrets it should know and not more.
    :param sub_proof: The proof from which to get a prover
    :param secrets_dict: The secret values to filter out before passing them to the prover
    """
    keys = set(sub_proof.secret_vars)
    secrets_for_prover = {}
    for s_name in secrets_dict.keys():
        if s_name in keys:
            secrets_for_prover[s_name] = secrets_dict[s_name]
    return sub_proof.get_prover(secrets_for_prover)


class OrProof(Proof):
    def __init__(self, *subproofs):
        """
        Constructs the Or conjunction of several subproofs.
        :param subproofs: An arbitrary number of proofs. 
        """
        if len(subproofs) < 2:
            raise Exception("OrProof needs >1 arguments !")

        self.subproofs = list(subproofs)

        self.generators = get_generators(self.subproofs)
        self.secret_vars = get_secret_vars(self.subproofs)
        # Construct a dictionary with the secret values we already know
        self.secret_values = {}
        for sec in self.secret_vars:
            if sec.value is not None:
                self.secret_values[sec] = sec.value
        self.simulation = False
        check_groups(self.secret_vars, self.generators)
        # For now we consider the same constraints as in the And Proof

    def get_proof_id(self):
        return ["Or", [sub.get_proof_id() for sub in self.subproofs]]

    def recompute_commitment(self, challenge, responses):
        """ 
        Recomputes the commitments, raises an Exception if the global challenge was not respected.
        :param challenge: The global challenge sent by the verifier.
        :param responses: A tuple (subchallenges, actual_responses) containing the subchallenges
        each proof used (ordered list), and a list of responses (also ordered)
        """
        # We retrieve the challenges, hidden in the responses tuple
        self.or_challenges = responses[0]
        responses = responses[1]
        comm = []
        # We check for challenge consistency i.e the constraint was respected
        if find_residual_chal(self.or_challenges, challenge, CHAL_LENGTH) != Bn(0):
            raise Exception("Inconsistent challenge")
        # Compute the list of commitments, one for each proof with its challenge and responses (in-order)
        for i in range(len(self.subproofs)):
            cur_proof = self.subproofs[i]
            comm.append(
                cur_proof.recompute_commitment(self.or_challenges[i], responses[i])
            )
        return comm

    def get_prover(self, secrets_dict={}):
        """
        Gets an OrProver, which is built on one legit prover constructed from a subproof picked at random among all possible candidates.
        """
        # First we update the dictionary we have with the additional secrets, and process it
        self.secret_values.update(secrets_dict)
        secrets_dict = self.secret_values
        if self.simulation == True or secrets_dict == {}:
            return None
        # Prepare the draw. Disqualify proofs with simulation parameter set to true
        candidates = {}
        for idx in range(len(self.subproofs)):
            if not self.subproofs[idx].simulation:
                candidates[idx] = self.subproofs[idx]
        if len(candidates) == 0:
            print("Cannot run an Or Proof if all elements are simulated")
            return None
        # Now choose a proof among the possible ones and try to get a prover from it.
        # If for some reason it does not work (e.g some secrets are missing), remove it
        # from the list of possible proofs and try again
        rd = random.SystemRandom()
        # We would appreciate a do...while here >:(
        possible = list(candidates.keys())
        self.chosen_idx = rd.choice(possible)
        # Feed the selected proof the secrets it needs if we have them, and try to get_prover
        valid_prover = sub_proof_prover(self.subproofs[self.chosen_idx], secrets_dict)
        while valid_prover is None:
            possible.remove(self.chosen_idx)
            # If there is no proof left, abort and say we cannot get a prover
            if len(possible) == 0:
                return None
            self.chosen_idx = rd.choice(possible)
            valid_prover = sub_proof_prover(
                self.subproofs[self.chosen_idx], secrets_dict
            )
        return OrProver(self, valid_prover)

    def get_verifier(self):
        return OrVerifier(self, [subp.get_verifier() for subp in self.subproofs])

    def check_or_flaw(self, forbidden_secrets=None):
        """ 
        Checks for appearance of reoccuring secrets both inside and outside an Or Proof.
        Raises an error if finds any. Method called from AndProof.check_or_flaw
        :param forbidden_secrets: A list of all the secrets in the mother proof.
        """
        if forbidden_secrets is None:
            return
        for secret in set(self.secret_vars):
            if forbidden_secrets.count(secret) > self.secret_vars.count(secret):
                raise Exception(
                    "Or flaw detected. Aborting. Try to flatten the proof to  \
                avoid shared secrets inside and outside an Or"
                )

    def simulate_proof(self, responses_dict=None, challenge=None):
        """
        Simulates an Or Proof. To do so, simulates the N-1 first subproofs, computes the complementary challenge
        and simulates the last proof using this challenge. Does not use the responses_dict passed as parameter since inside an Or Proof
        responses consistency is not required between subproofs.
        :param challenge: The global challenge, equal to the sum of all the subchallenges mod chal bitlength.
        :param responses_dict: A dictionary of responses to enforce for consistency. Useless hiere, kept to have the same prototype for all simulate_proof methods.
        """
        if challenge is None:
            challenge = chal_randbits(CHAL_LENGTH)
        com = []
        resp = []
        or_chals = []
        precom = []
        # Generate one simulation at a time and update a list of each attribute
        for index in range(len(self.subproofs) - 1):
            transcript = self.subproofs[index].simulate_proof()
            com.append(transcript.commitment)
            resp.append(transcript.responses)
            or_chals.append(transcript.challenge)
            precom.append(transcript.precommitment)
        # Generate the last simulation
        final_chal = find_residual_chal(or_chals, challenge, CHAL_LENGTH)
        or_chals.append(final_chal)
        trfinal = self.subproofs[index + 1].simulate_proof(challenge=final_chal)
        com.append(trfinal.commitment)
        resp.append(trfinal.responses)
        precom.append(trfinal.precommitment)
        # Pack everything into a SimulationTranscript, pack the or_challenges in the response field
        return SimulationTranscript(com, challenge, (or_chals, resp), precom)


class OrProver(Prover):
    def __init__(self, proof, subprover):
        """
        Constructs a Prover for the Or Proof. Is built with only one subprover, and needs to have access to the index of the corresponding subproof in its mother proof.
        Runs all the simulations for the other proofs and stores them.
        """
        self.subprover = subprover
        self.proof = proof
        self.true_prover_idx = self.proof.chosen_idx
        # Create a list to store the SimulationTranscripts
        self.simulations = []
        self.setup_simulations()

    def setup_simulations(self):
        """
        Runs all the required simulations and stores them.
        """
        for index in range(len(self.proof.subproofs)):
            if index != self.true_prover_idx:
                cur = self.proof.subproofs[index].simulate_proof()
                self.simulations.append(cur)

    def precommit(self):
        """
        Generates a precommitment for the legit subprover, and gathers the precommitments from the stored simulations.
        Outputs a list of the precommitments needed by the subproofs if any. Else, returns None.
        """
        precommitment = []
        for index in range(len(self.proof.subproofs)):
            if index == self.true_prover_idx:
                precommitment.append(self.subprover.precommit())
            else:
                if index > self.true_prover_idx:
                    index1 = index - 1
                else:
                    index1 = index
                precommitment.append(self.simulations[index1].precommitment)
        if not any(precommitment):
            return None
        return precommitment

    def internal_commit(self, randomizers_dict=None):
        """ 
        Commits from the subprover, gathers the commitments from the stored simulations. Packs into a list.
        :param randomizers_dict: A dictionary of randomizers to use for responses consistency. Not used in this proof. Parameter kept so all internal_commit methods have the same prototype.
        """
        commitment = []
        for index in range(len(self.proof.subproofs)):
            if index == self.true_prover_idx:
                commitment.append(self.subprover.internal_commit())
            else:
                if index > self.true_prover_idx:
                    index1 = index - 1
                else:
                    index1 = index
                commitment.append(self.simulations[index1].commitment)
        return commitment

    def compute_response(self, challenge):
        """
        Computes the complementary challenge with respect to the received global challenge and the list of challenges used in the stored simulations.
        Computes the responses of the subprover using this auxiliary challenge, gathers the responses from the stored simulations.
        Returns both the complete list of subchallenges (included the auxiliary challenge) and the list of responses, both ordered.
        :param challenge: The global challenge to use. All subchallenges must add to this one.
        """
        residual_chal = find_residual_chal(
            [el.challenge for el in self.simulations], challenge, CHAL_LENGTH
        )
        response = []
        challenges = []
        for index in range(len(self.proof.subproofs)):
            if index == self.true_prover_idx:
                challenges.append(residual_chal)
                response.append(self.subprover.compute_response(residual_chal))
            else:
                # Note len(simulations) = len(subproofs) - 1 !
                if index > self.true_prover_idx:
                    index1 = index - 1
                else:
                    index1 = index
                challenges.append(self.simulations[index1].challenge)
                response.append(self.simulations[index1].responses)

        # We carry the or challenges in a tuple, will be unpacked by the verifier calling recompute_commitment
        return (challenges, response)


class OrVerifier(Verifier):
    def __init__(self, proof, subverifiers):
        """
        Constructs a Verifier for the Or Proof. Is built on a list of subverifiers, which will unpack the received attributes.
        """
        self.subs = subverifiers
        self.proof = proof

    def process_precommitment(self, precommitment):
        """
        Reads the received list of precommitments (or None if non applicable) and distributes them to the subverifiers so they can finalize their proof construction if necessary.
        :param precommitment: A list of all required precommitments, ordered.
        """
        if precommitment is None:
            return
        for idx in range(len(self.subs)):
            self.subs[idx].process_precommitment(precommitment[idx])

    def check_responses_consistency(self, responses, responses_dict={}):
        """
        Checks that for a same secret, response are actually the same. 
        Since every member is run with its own challenge, it is enough that one member is consistent within itself.
        :param responses: a tuple (subchallenges, actual_responses) from which we extract only the actual responses for each subverifier.
        """
        for idx in range(len(self.subs)):
            if not self.subs[idx].check_responses_consistency(responses[1][idx], {}):
                return False
        return True


class AndProof(Proof):
    """
    A Proof representing the And conjunction of several subproofs.
    """

    def __init__(self, *subproofs):
        """
        Constructs the Or conjunction of several subproofs.
        :param subproofs: An arbitrary number of proofs. 
        """
        if len(subproofs) < 2:
            raise Exception("AndProof needs >1 arguments !")

        self.subproofs = list(subproofs)
        self.generators = get_generators(self.subproofs)
        self.secret_vars = get_secret_vars(self.subproofs)
        # Construct a dictionary with the secret values we already know
        self.secret_values = {}
        for sec in self.secret_vars:
            if sec.value is not None:
                self.secret_values[sec] = sec.value
        self.simulation = False
        # Check reoccuring secrets are related to generators of same group order
        check_groups(self.secret_vars, self.generators)
        # Raise an error when detecting a secret occuring both inside and outside an Or Proof
        self.check_or_flaw()

    def recompute_commitment(self, challenge, andresp):
        """
        Recomputes the commitment consistent with the given challenge and response, as a list of commitments of the subproofs.
        :param challenge: The challenge to use in the proof
        :param andresp: A list of responses (themselves being lists), ordered as the list of subproofs.
        """
        comm = []
        for i in range(len(self.subproofs)):
            cur_proof = self.subproofs[i]
            comm.append(cur_proof.recompute_commitment(challenge, andresp[i]))
        return comm

    def get_prover(self, secrets_dict={}):
        """ 
        Constructs a Prover for the And Proof, which is a list of the Provers related to each subproof, in order.
        If any of the collected Provers is invalid (None), returns None.
        """
        # First we update the dictionary we have with the additional secrets, and process it
        self.secret_values.update(secrets_dict)
        secrets_dict = self.secret_values
        if self.simulation == True or secrets_dict == {}:
            return None

        subs = [
            sub_proof_prover(sub_proof, secrets_dict) for sub_proof in self.subproofs
        ]
        if None in subs:
            return None
        return AndProver(self, subs)

    def get_verifier(self):
        """
        Constructs a Verifier for the And Proof, based on a list of the Verifiers of each subproof.
        """
        return AndVerifier(self, [subp.get_verifier() for subp in self.subproofs])

    def get_proof_id(self):
        return ["And", [sub.get_proof_id() for sub in self.subproofs]]

    def get_randomizers(self) -> dict:
        """
        Creates a dictionary of randomizers by querying the subproofs dicts and merging them
        """
        random_vals = {}
        # Pair each Secret to one generator. Overwrites when a Secret reoccurs but since the associated generators should yield groups of same order it's fine
        dict_name_gen = dict(zip(self.secret_vars, self.generators))
        # Pair each Secret to a randomizer
        for u in dict_name_gen:
            random_vals[u] = dict_name_gen[u].group.order().random()
        return random_vals

    def simulate_proof(self, responses_dict=None, challenge=None):
        """
        Simulates the And Proof, i.e draws a global challenge, a global dictionary of responses (for consistency) and simulates each subproof.
        Gathers the commitments, and pack everything into a unique SimulationTranscript
        :param responses_dict: A dictionary of responses to enforce (could come from an upper And Proof, for example). Draw one if None.
        :param challenge: The challenge to use in the proof. Draw one if None.
        """
        # Fill the missing positions of the responses dictionary
        responses_dict = self.update_randomizers(responses_dict)
        if challenge is None:
            challenge = chal_randbits(CHAL_LENGTH)
        com = []
        resp = []
        precom = []
        # Simulate all subproofs and gather their attributes, repack them in a unique SimulationTranscript
        for subp in self.subproofs:
            simulation = subp.simulate_proof(responses_dict, challenge)
            com.append(simulation.commitment)
            resp.append(simulation.responses)
            precom.append(simulation.precommitment)
        return SimulationTranscript(com, challenge, resp, precom)

    def check_or_flaw(self, forbidden_secrets=None):
        """ 
        Checks for appearance of reoccuring secrets both inside and outside an Or Proof.
        Raises an error if finds any. This method only sets the list of all secrets in the tree and triggers a depth-search first for Or Proofs
        :param forbidden_secrets: A list of all the secrets in the mother proof.
        """
        if forbidden_secrets is None:
            forbidden_secrets = self.secret_vars.copy()
        for subp in self.subproofs:
            subp.check_or_flaw(forbidden_secrets)


class AndProver(Prover):
    def __init__(self, proof, subprovers):
        """
        Constructs a Prover for an And Proof, from a list of valid subprovers.
        """
        self.subs = subprovers
        self.proof = proof

    def precommit(self):
        """
        Computes the precommitment for an And Proof, i.e a list of the precommitments of the subprovers.
        If not applicable (not subprover outputs a precommitment), returns None.
        """
        precommitment = []
        for idx in range(len(self.subs)):
            # Collects precommitments one by one
            subprecom = self.subs[idx].precommit()
            if subprecom is not None:
                if len(precommitment) == 0:
                    precommitment = [None] * len(self.subs)
                precommitment[idx] = subprecom
        # If any precommitment is valid, return the list. If all were None, return None
        return precommitment if len(precommitment) != 0 else None

    def internal_commit(self, randomizers_dict=None):
        """
        Computes the commitment i.e a list of the commitments of the subprovers.
        :param randomizers_dict: Randomizers to enforce to ensure responses consistency, which every subproof must use.
        """
        # Fill the missing values if necessary
        randomizers_dict = self.proof.update_randomizers(randomizers_dict)
        self.commitment = []
        for subp in self.subs:
            self.commitment.append(
                subp.internal_commit(randomizers_dict=randomizers_dict)
            )
        return self.commitment

    def compute_response(self, challenge):
        """
        Returns a list of the responses of each subprover.
        """
        return [subp.compute_response(challenge) for subp in self.subs]


class AndVerifier(Verifier):
    def __init__(self, proof, subverifiers):
        """
        Constructs a Verifier for the And Proof, with a list of subverifiers.
        """
        self.subs = subverifiers
        self.proof = proof

    def send_challenge(self, commitment, mute=False):
        """
        Stores the received commitment and generates a challenge. Checks the received hashed statement matches the one of the current proof.
        Only called at the highest level or in embedded proofs working with precommitments.
        :param commitment: A tuple (statement, actual_commitment) with actual_commitment a list of commitments, one for each subproof.
        :param mute: Optional parameter to deactivate the statement check. In this case, the commitment parameter is simply the actual commitment. Useful in 2-level proofs for which we don't check the inner statements.
        """
        if mute:
            self.commitment = commitment
        else:
            statement, self.commitment = commitment
            self.proof.check_statement(statement)
        self.challenge = chal_randbits(CHAL_LENGTH)
        return self.challenge

    def check_responses_consistency(self, responses, responses_dict={}):
        """
        Checks the responses are consistent for reoccurring secret names. 
        Iterates through the subverifiers, gives them the responses related to them and constructs a response dictionary (with respect to secret names).
        If an inconsistency if found during this build, an error code is returned.
        :param responses: The received list of responses for each subproof.
        :param responses_dict: The dictionary to construct and use for comparison.
        """
        for i in range(len(self.subs)):
            if not self.subs[i].check_responses_consistency(
                responses[i], responses_dict
            ):
                return False
        return True

    def process_precommitment(self, precommitment):
        """
        Receives a list of precommitments for the subproofs (or None) and distributes them to the subverifiers.
        """
        if precommitment is None:
            return
        for idx in range(len(self.subs)):
            self.subs[idx].process_precommitment(precommitment[idx])

    def check_adequate_lhs(self):
        """
        Check that all the left-hand sides of the proofs have a coherent value.
        For instance, it will return False if a DLRepNotEqualProof is in the tree and
        if it is about to prove its components are in fact equal.
        This allows to not waste computation time in running useless verifications.
        """
        for sub in self.subs:
            if not sub.check_adequate_lhs():
                return False
        return True
